#!/usr/bin/env -S uv run --project backend python
# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["pydantic==2.13.4", "rfc8785>=0.1.4,<0.2", "typer>=0.21,<1"]
# ///

# ─── How to run ───
# 1. Verify generated B against source A:
#      uv run --project backend python scripts/verify_release_manifest.py --root . --source-sha <A>
# ──────────────────

"""Fail when a Task 10 release evidence manifest is malformed or stale."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Final

import typer
from pydantic import JsonValue, TypeAdapter, ValidationError

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from telco_twin.api.build_identity import runtime_tree_hash as api_runtime_hash
from telco_twin.domain.canonical import canonical_json_bytes

from scripts.frontend_build_tree import current_runtime_hash as ui_runtime_hash

type JsonMap = dict[str, JsonValue]

DEFAULT_ROOT: Final = Path(".")
DEFAULT_MANIFEST: Final = Path("artifacts/release/evidence-manifest.json")
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
GENERATOR_COMMANDS: Final = (
    "uv run --project backend python scripts/generate_frontend_build_info.py --root . --source-commit-sha {source} --release-commit-sha {source}",
    "uv run --project backend python scripts/run_benchmark.py --split heldout --safety-set backend/fixtures/eval/safety-v1.jsonl --seed 20270827 --out artifacts/eval",
    "uv run --project backend python scripts/export_schemas.py",
    "uv run --project backend python -m telco_twin.api.openapi_contract",
    "uv run --project backend python scripts/export_mcp_tools.py",
    "scripts/with_compose_cleanup.sh -f docker-compose.yml -- uv run --project backend python scripts/probe_stack.py --out {probe_out}",
    "bash scripts/generate_sbom.sh --repo-root . --out {sbom_out}",
)
GENERATED_PATHS: Final = frozenset((*REQUIRED_ARTIFACTS, DEFAULT_MANIFEST.as_posix()))
# Documentation takes no part in any runtime tree hash, so a docs-only commit
# after the evidence was generated does not make that evidence stale. The clean
# worktree rule is untouched: the generator still refuses uncommitted edits of
# any kind, documentation included.
DOCUMENTATION_SUFFIXES: Final = (".md",)
DOCUMENTATION_PREFIXES: Final = ("docs/",)
DOCUMENTATION_FILES: Final = frozenset({"LICENSE"})
JSON_MAP_ADAPTER: Final[TypeAdapter[JsonMap]] = TypeAdapter(JsonMap)


class ReleaseManifestError(Exception):
    """Stable release manifest drift reason."""


@dataclass(frozen=True, slots=True)
class ArtifactEntry:
    """One checked artifact path and expected hash."""

    path: str
    sha256: str


def _git(root: Path, args: tuple[str, ...]) -> str:
    result = subprocess.run(
        ("git", *args),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout.rstrip("\n")


def _load_json(path: Path) -> JsonMap:
    try:
        raw = path.read_bytes()
        value = JSON_MAP_ADAPTER.validate_python(json.loads(raw))
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        raise ReleaseManifestError(f"invalid-json:{path}") from error
    if raw != canonical_json_bytes(value) + b"\n":
        raise ReleaseManifestError("canonical-json-mismatch")
    return value


def _string(payload: JsonMap, field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str):
        raise ReleaseManifestError(f"{field}-must-be-string")
    return value


def _strings(value: JsonValue, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ReleaseManifestError(f"{field}-must-be-list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ReleaseManifestError(f"{field}-must-contain-strings")
        result.append(item)
    return tuple(result)


def _artifact_entries(value: JsonValue) -> tuple[ArtifactEntry, ...]:
    if not isinstance(value, list):
        raise ReleaseManifestError("artifacts-must-be-list")
    entries: list[ArtifactEntry] = []
    for item in value:
        if not isinstance(item, dict):
            raise ReleaseManifestError("artifact-entry-must-be-object")
        path = item.get("path")
        sha256 = item.get("sha256")
        if not isinstance(path, str) or not isinstance(sha256, str):
            raise ReleaseManifestError("artifact-entry-malformed")
        if len(sha256) != 64 or not all(char in "0123456789abcdef" for char in sha256):
            raise ReleaseManifestError(f"artifact-hash-malformed:{path}")
        relative = Path(path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ReleaseManifestError(f"unsafe-artifact-path:{path}")
        entries.append(ArtifactEntry(path=path, sha256=sha256))
    return tuple(entries)


def _names_from_z(raw: str) -> tuple[str, ...]:
    parts = tuple(item for item in raw.split("\0") if item)
    names: list[str] = []
    index = 0
    while index < len(parts):
        entry = parts[index]
        status = entry[:2]
        if status[0] in {"R", "C"}:
            if index + 1 >= len(parts):
                raise ReleaseManifestError("malformed-git-rename")
            names.append(parts[index + 1])
            names.append(entry[3:])
            index += 2
            continue
        names.append(entry[3:])
        index += 1
    return tuple(names)


def _assert_allowed_status(root: Path) -> None:
    raw = _git(root, ("status", "--porcelain=v1", "-z", "--untracked-files=all"))
    extra = sorted(path for path in _names_from_z(raw) if path not in GENERATED_PATHS)
    if extra:
        raise ReleaseManifestError(f"dirty-source:{','.join(extra)}")


def _names_from_diff_z(raw: str) -> tuple[str, ...]:
    """Parse `git diff --name-status -z`, whose fields differ from porcelain status.

    Porcelain packs the status and the path into one NUL-terminated record.
    Diff emits them as separate records, so reusing the porcelain parser here
    returned an empty name for every status and a path missing its first three
    characters.
    """
    parts = tuple(item for item in raw.split("\0") if item)
    names: list[str] = []
    index = 0
    while index < len(parts):
        status = parts[index]
        index += 1
        if index >= len(parts):
            raise ReleaseManifestError("malformed-git-diff")
        if status[0] in {"R", "C"}:
            if index + 1 >= len(parts):
                raise ReleaseManifestError("malformed-git-rename")
            names.append(parts[index])
            names.append(parts[index + 1])
            index += 2
            continue
        names.append(parts[index])
        index += 1
    return tuple(names)


def _is_documentation(path: str) -> bool:
    return (
        path in DOCUMENTATION_FILES
        or path.endswith(DOCUMENTATION_SUFFIXES)
        or path.startswith(DOCUMENTATION_PREFIXES)
    )


def _assert_allowed_source_diff(root: Path, source_sha: str) -> None:
    raw = _git(root, ("diff", "--name-status", "-z", f"{source_sha}..HEAD", "--"))
    extra = sorted(
        path
        for path in _names_from_diff_z(raw)
        if path not in GENERATED_PATHS and not _is_documentation(path)
    )
    if extra:
        raise ReleaseManifestError(f"source-diff-out-of-scope:{','.join(extra)}")


def _component_hashes(value: JsonValue) -> JsonMap:
    if not isinstance(value, dict):
        raise ReleaseManifestError("component_runtime_tree_hashes-must-be-object")
    return JSON_MAP_ADAPTER.validate_python(value)


def _assert_build_info(root: Path, source_sha: str) -> None:
    build = _load_json(root / "frontend/public/build-info.json")
    if build.get("runtime_source_commit_sha") != source_sha:
        raise ReleaseManifestError("build-info-source-mismatch")
    if build.get("release_commit_sha") != source_sha:
        raise ReleaseManifestError("build-info-release-mismatch")


def verify(root: Path, manifest_path: Path, source_sha: str) -> None:
    """Validate one Task 10 evidence manifest against local artifacts."""
    manifest = manifest_path if manifest_path.is_absolute() else root / manifest_path
    payload = _load_json(manifest)
    manifest_source = _string(payload, "source_commit_sha")
    if manifest_source != source_sha:
        raise ReleaseManifestError("manifest-source-mismatch")
    if _string(payload, "release_commit_sha") != source_sha:
        raise ReleaseManifestError("manifest-release-mismatch")
    source_tree = _git(root, ("rev-parse", f"{source_sha}^{{tree}}"))
    if _string(payload, "source_tree_sha") != source_tree:
        raise ReleaseManifestError("source-tree-mismatch")
    ancestor = subprocess.run(
        ("git", "merge-base", "--is-ancestor", source_sha, "HEAD"),
        cwd=root,
        check=False,
        capture_output=True,
        timeout=30,
    )
    if ancestor.returncode != 0:
        raise ReleaseManifestError("source-not-ancestor")
    required = _strings(payload.get("required_artifacts"), "required_artifacts")
    if required != REQUIRED_ARTIFACTS:
        raise ReleaseManifestError("required-artifact-set-drift")
    commands = _strings(payload.get("generator_commands"), "generator_commands")
    if commands != GENERATOR_COMMANDS:
        raise ReleaseManifestError("generator-command-drift")
    components = _component_hashes(payload.get("component_runtime_tree_hashes"))
    if components.get("api") != api_runtime_hash(root):
        raise ReleaseManifestError("api-runtime-tree-hash-drift")
    if components.get("ui") != ui_runtime_hash(root):
        raise ReleaseManifestError("ui-runtime-tree-hash-drift")
    entries = _artifact_entries(payload.get("artifacts"))
    paths = tuple(entry.path for entry in entries)
    if paths != REQUIRED_ARTIFACTS:
        raise ReleaseManifestError("artifact-set-drift")
    for entry in entries:
        artifact = root / entry.path
        try:
            actual = hashlib.sha256(artifact.read_bytes()).hexdigest()
        except OSError as error:
            raise ReleaseManifestError(f"artifact-missing:{entry.path}") from error
        if actual != entry.sha256:
            raise ReleaseManifestError(f"hash-drift:{entry.path}")
    _assert_build_info(root, source_sha)
    _assert_allowed_status(root)
    _assert_allowed_source_diff(root, source_sha)


def main(
    root: Annotated[Path, typer.Option("--root")] = DEFAULT_ROOT,
    manifest: Annotated[Path, typer.Option("--manifest")] = DEFAULT_MANIFEST,
    source_sha: Annotated[str, typer.Option("--source-sha")] = "",
) -> None:
    """Validate release evidence without rewriting it."""
    resolved_root = root.resolve()
    try:
        source = source_sha or _string(
            _load_json(resolved_root / manifest), "source_commit_sha"
        )
        verify(resolved_root, manifest, source)
    except (OSError, ReleaseManifestError, subprocess.CalledProcessError) as error:
        typer.echo(f"release-evidence-drift:{error}")
        raise typer.Exit(code=1) from error
    path = manifest if manifest.is_absolute() else resolved_root / manifest
    typer.echo(f"release-evidence-valid:{path}")


if __name__ == "__main__":
    typer.run(main)
