#!/usr/bin/env -S uv run --project backend python
# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["pydantic==2.13.4", "rfc8785>=0.1.4,<0.2", "typer>=0.21,<1"]
# ///

# ─── How to run ───
# 1. Generate from clean source A:
#      uv run --project backend python scripts/generate_release_evidence.py --root . --source-sha <A>
# 2. Verify generated B:
#      uv run --project backend python scripts/verify_release_manifest.py --root . --source-sha <A>
# ──────────────────

"""Generate the Task 10 release evidence transaction from clean source A."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Final

import typer
from pydantic import JsonValue

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from telco_twin.api.build_identity import runtime_tree_hash as api_runtime_hash
from telco_twin.domain.canonical import JSON_VALUE_ADAPTER, canonical_json_bytes

from scripts.frontend_build_tree import current_runtime_hash as ui_runtime_hash

type Command = tuple[str, ...]
type JsonMap = dict[str, JsonValue]

DEFAULT_ROOT: Final = Path(".")
MANIFEST_PATH: Final = Path("artifacts/release/evidence-manifest.json")
REQUIRED_ARTIFACTS: Final = (
    "artifacts/contracts/openapi.json",
    "artifacts/contracts/mcp-tools.json",
    "artifacts/eval/counterfactual.json",
    "artifacts/eval/diagnosis-summary.json",
    "artifacts/eval/diagnosis.jsonl",
    "artifacts/eval/replay-hashes.json",
    "artifacts/eval/safety-gate.json",
    "artifacts/probe/local-stack-probe.json",
    "frontend/public/build-info.json",
    "artifacts/security/component-inventory.json",
)
EVAL_FILES: Final = REQUIRED_ARTIFACTS[2:7]
GENERATOR_COMMANDS: Final = (
    "uv run --project backend python scripts/generate_frontend_build_info.py --root . --source-commit-sha {source} --release-commit-sha {source}",
    "uv run --project backend python scripts/run_benchmark.py --split heldout --safety-set backend/fixtures/eval/safety-v1.jsonl --seed 20270827 --out artifacts/eval",
    "uv run --project backend python scripts/export_schemas.py",
    "uv run --project backend python -m telco_twin.api.openapi_contract",
    "uv run --project backend python scripts/export_mcp_tools.py",
    "scripts/with_compose_cleanup.sh -f docker-compose.yml -- uv run --project backend python scripts/probe_stack.py --out {probe_out}",
    "bash scripts/generate_sbom.sh --repo-root . --out {sbom_out}",
)
GENERATED_PATHS: Final = (*REQUIRED_ARTIFACTS, MANIFEST_PATH.as_posix())


class ReleaseEvidenceError(Exception):
    """Stable CLI error for deterministic release evidence generation."""


@dataclass(frozen=True, slots=True)
class SavedFile:
    """One original generated output captured before transaction mutation."""

    relative: str
    data: bytes | None


def _run(root: Path, command: Command) -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(root), environment.get("PYTHONPATH", "")) if part
    )
    _ = subprocess.run(
        command,
        cwd=root,
        check=True,
        timeout=900,
        env=environment,
    )


def _git(root: Path, args: Command) -> str:
    result = subprocess.run(
        ("git", *args),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout.strip()


def _status_entries(root: Path) -> tuple[str, ...]:
    result = subprocess.run(
        ("git", "status", "--porcelain=v1", "-z", "--untracked-files=all"),
        cwd=root,
        check=True,
        capture_output=True,
        timeout=30,
    )
    return tuple(
        chunk.decode("utf-8", errors="strict")
        for chunk in result.stdout.split(b"\0")
        if chunk
    )


def _require_clean_source(root: Path, source_sha: str) -> None:
    head = _git(root, ("rev-parse", "HEAD"))
    if head != source_sha:
        raise ReleaseEvidenceError(f"source-head-mismatch:{head}")
    entries = _status_entries(root)
    if entries:
        raise ReleaseEvidenceError(f"dirty-source:{','.join(entries)}")


def _snapshot(root: Path) -> tuple[SavedFile, ...]:
    saved: list[SavedFile] = []
    for relative in GENERATED_PATHS:
        path = root / relative
        saved.append(
            SavedFile(
                relative=relative, data=path.read_bytes() if path.exists() else None
            )
        )
    return tuple(saved)


def _restore(root: Path, saved: tuple[SavedFile, ...]) -> None:
    for item in saved:
        path = root / item.relative
        if item.data is None:
            path.unlink(missing_ok=True)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(path, item.data)


def _atomic_write(path: Path, encoded: bytes) -> None:
    """Publish one file atomically from a same-directory staging file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    staging: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as stream:
            staging = Path(stream.name)
            _ = stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staging, path)
    except OSError:
        if staging is not None:
            staging.unlink(missing_ok=True)
        raise


def _stage_files(root: Path, stage: Path, relatives: tuple[str, ...]) -> None:
    for relative in relatives:
        source = root / relative
        if not source.is_file():
            raise ReleaseEvidenceError(f"missing-generated-artifact:{relative}")
        target = stage / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        _ = shutil.copy2(source, target)


def _install_stage_files(root: Path, stage: Path, relatives: tuple[str, ...]) -> None:
    for relative in relatives:
        _atomic_write(root / relative, (stage / relative).read_bytes())


def _require_prior_eval_dir_clean(root: Path) -> None:
    eval_dir = root / "artifacts/eval"
    if not eval_dir.exists():
        return
    files = {
        path.relative_to(root).as_posix()
        for path in eval_dir.rglob("*")
        if path.is_file()
    }
    expected = set(EVAL_FILES)
    if files != expected:
        extra = sorted(files - expected)
        missing = sorted(expected - files)
        details = ",".join((*extra, *(f"missing:{item}" for item in missing)))
        raise ReleaseEvidenceError(f"prior-eval-dir-drift:{details}")


def _remove_eval_dir(root: Path) -> None:
    shutil.rmtree(root / "artifacts/eval", ignore_errors=True)


def _render_manifest(root: Path, source_sha: str, stage: Path) -> bytes:
    source_tree_sha = _git(root, ("rev-parse", f"{source_sha}^{{tree}}"))
    entries: list[JsonMap] = []
    for relative in REQUIRED_ARTIFACTS:
        entries.append(
            {
                "path": relative,
                "sha256": hashlib.sha256((stage / relative).read_bytes()).hexdigest(),
            }
        )
    payload = {
        "schema_version": "1.0",
        "source_commit_sha": source_sha,
        "release_commit_sha": source_sha,
        "source_tree_sha": source_tree_sha,
        "component_runtime_tree_hashes": {
            "api": api_runtime_hash(root),
            "ui": ui_runtime_hash(root),
        },
        "required_artifacts": list(REQUIRED_ARTIFACTS),
        "generator_commands": list(GENERATOR_COMMANDS),
        "artifacts": entries,
    }
    parsed = JSON_VALUE_ADAPTER.validate_python(payload)
    return canonical_json_bytes(parsed) + b"\n"


def _generate_into_stage(
    root: Path, source_sha: str, stage: Path, saved: tuple[SavedFile, ...]
) -> None:
    _run(
        root,
        (
            "uv",
            "run",
            "--project",
            "backend",
            "python",
            "scripts/generate_frontend_build_info.py",
            "--root",
            ".",
            "--source-commit-sha",
            source_sha,
            "--release-commit-sha",
            source_sha,
        ),
    )
    _stage_files(root, stage, ("frontend/public/build-info.json",))
    _restore(root, saved)

    _require_prior_eval_dir_clean(root)
    _remove_eval_dir(root)
    _run(
        root,
        (
            "uv",
            "run",
            "--project",
            "backend",
            "python",
            "scripts/run_benchmark.py",
            "--split",
            "heldout",
            "--safety-set",
            "backend/fixtures/eval/safety-v1.jsonl",
            "--seed",
            "20270827",
            "--out",
            "artifacts/eval",
        ),
    )
    _stage_files(root, stage, EVAL_FILES)
    _restore(root, saved)

    _run(
        root,
        ("uv", "run", "--project", "backend", "python", "scripts/export_schemas.py"),
    )
    _run(
        root,
        (
            "uv",
            "run",
            "--project",
            "backend",
            "python",
            "-m",
            "telco_twin.api.openapi_contract",
        ),
    )
    _run(
        root,
        ("uv", "run", "--project", "backend", "python", "scripts/export_mcp_tools.py"),
    )
    _stage_files(root, stage, REQUIRED_ARTIFACTS[0:2])
    _restore(root, saved)

    _install_stage_files(root, stage, ("frontend/public/build-info.json",))
    probe = stage / "artifacts/probe/local-stack-probe.json"
    sbom = stage / "artifacts/security/component-inventory.json"
    _run(
        root,
        (
            "scripts/with_compose_cleanup.sh",
            "-f",
            "docker-compose.yml",
            "--",
            "uv",
            "run",
            "--project",
            "backend",
            "python",
            "scripts/probe_stack.py",
            "--out",
            str(probe),
        ),
    )
    _restore(root, saved)
    _run(
        root,
        ("bash", "scripts/generate_sbom.sh", "--repo-root", ".", "--out", str(sbom)),
    )


def generate(root: Path, source_sha: str) -> Path:
    """Generate every Task 10 artifact and publish only after validation."""
    _require_clean_source(root, source_sha)
    saved = _snapshot(root)
    with tempfile.TemporaryDirectory(prefix="task10-release-evidence-") as temp:
        stage = Path(temp)
        try:
            _generate_into_stage(root, source_sha, stage, saved)
            manifest = stage / MANIFEST_PATH
            for relative in REQUIRED_ARTIFACTS:
                if not (stage / relative).is_file():
                    raise ReleaseEvidenceError(f"missing-staged-artifact:{relative}")
            _atomic_write(manifest, _render_manifest(root, source_sha, stage))
            _restore(root, saved)
            _install_stage_files(root, stage, REQUIRED_ARTIFACTS)
            _atomic_write(root / MANIFEST_PATH, manifest.read_bytes())
        except (OSError, ReleaseEvidenceError, subprocess.CalledProcessError):
            _restore(root, saved)
            raise
    return root / MANIFEST_PATH


def main(
    root: Annotated[Path, typer.Option("--root")] = DEFAULT_ROOT,
    source_sha: Annotated[str, typer.Option("--source-sha")] = "",
) -> None:
    """Generate Task 10 release evidence in one clean source checkout."""
    resolved_root = root.resolve()
    try:
        source = source_sha or _git(resolved_root, ("rev-parse", "HEAD"))
        manifest = generate(resolved_root, source)
    except (OSError, ReleaseEvidenceError, subprocess.CalledProcessError) as error:
        typer.echo(f"release-evidence-error:{error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"release-evidence-generated:{manifest.relative_to(resolved_root)}")


if __name__ == "__main__":
    typer.run(main)
