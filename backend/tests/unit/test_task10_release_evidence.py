"""Task 10 release evidence manifest verification contracts."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

import pytest

from telco_twin.api.build_identity import runtime_tree_hash as api_runtime_hash
from telco_twin.domain.canonical import JSON_VALUE_ADAPTER, canonical_json_bytes

if TYPE_CHECKING:
    from collections.abc import Callable

REPO_ROOT: Final = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from scripts import frontend_build_tree  # noqa: E402
from scripts import generate_release_evidence as generator  # noqa: E402
from scripts import verify_release_manifest as verifier  # noqa: E402

VERIFY_SCRIPT: Final = REPO_ROOT / "scripts/verify_release_manifest.py"
GENERATE_SCRIPT: Final = REPO_ROOT / "scripts/generate_release_evidence.py"
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
    (
        "uv run --project backend python scripts/generate_frontend_build_info.py "
        "--root . --source-commit-sha {source} --release-commit-sha {source}"
    ),
    (
        "uv run --project backend python scripts/run_benchmark.py "
        "--split heldout --safety-set backend/fixtures/eval/safety-v1.jsonl "
        "--seed 20270827 --out artifacts/eval"
    ),
    "uv run --project backend python scripts/export_schemas.py",
    "uv run --project backend python -m telco_twin.api.openapi_contract",
    "uv run --project backend python scripts/export_mcp_tools.py",
    (
        "scripts/with_compose_cleanup.sh -f docker-compose.yml -- "
        "uv run --project backend python scripts/probe_stack.py --out {probe_out}"
    ),
    "bash scripts/generate_sbom.sh --repo-root . --out {sbom_out}",
)


def run_script(script: Path, root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run one Task 10 CLI with imports pinned to the repository under test."""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join((str(REPO_ROOT / "backend/src"), str(REPO_ROOT)))
    return subprocess.run(
        [sys.executable, str(script), "--root", str(root), *args],
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_release_evidence_clis_bootstrap_repo_imports_without_pythonpath() -> None:
    # Given: the documented direct CLI boundary without a caller-provided import path.
    environment = dict(os.environ)
    _ = environment.pop("PYTHONPATH", None)

    # When: each Task 10 evidence CLI starts from the repository root.
    results = tuple(
        subprocess.run(
            [sys.executable, str(script), "--help"],
            cwd=REPO_ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        for script in (GENERATE_SCRIPT, VERIFY_SCRIPT)
    )

    # Then: both executable scripts resolve the repo-local scripts package themselves.
    assert all(result.returncode == 0 for result in results), "\n".join(
        result.stdout + result.stderr for result in results
    )


def git(root: Path, *args: str) -> str:
    """Run one Git command inside a temporary fixture repository."""
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.stdout.strip()


def init_repo(root: Path) -> str:
    """Create a minimal clean Git repository and return its HEAD SHA."""
    _ = git(root, "init", "--quiet")
    _ = git(root, "config", "user.name", "Task 10")
    _ = git(root, "config", "user.email", "task10@example.invalid")
    files = {
        "README.md": "fixture\n",
        "backend/src/app.py": "VALUE = 1\n",
        "backend/pyproject.toml": "[project]\nname='fixture'\nversion='0.1.0'\n",
        "backend/uv.lock": "version = 1\n",
        "specs/schemas/example.schema.json": '{"type":"object"}\n',
        "frontend/package.json": '{"name":"fixture-ui"}\n',
        "frontend/pnpm-lock.yaml": "lockfileVersion: '9.0'\npackages:\n  left-pad@1.3.0:\n",
        "frontend/pnpm-workspace.yaml": "packages:\n  - .\n",
        "frontend/src/main.tsx": "export const value = 1;\n",
        "frontend/tsconfig.json": '{"compilerOptions":{}}\n',
    }
    for relative, body in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_text(body, encoding="utf-8")
    _ = git(root, "add", ".")
    _ = git(root, "commit", "--quiet", "-m", "fixture")
    return git(root, "rev-parse", "HEAD")


def write_required_artifacts(root: Path) -> list[dict[str, str]]:
    """Write every required artifact and return its manifest entries."""
    entries: list[dict[str, str]] = []
    for relative in REQUIRED_ARTIFACTS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative == "frontend/public/build-info.json":
            source = git(root, "rev-parse", "HEAD")
            body = {
                "runtime_source_commit_sha": source,
                "release_commit_sha": source,
                "schema_version": "1.0",
            }
            _ = path.write_bytes(
                canonical_json_bytes(JSON_VALUE_ADAPTER.validate_python(body)) + b"\n"
            )
        elif relative.endswith(".jsonl"):
            _ = path.write_text('{"row":1}\n', encoding="utf-8")
        else:
            _ = path.write_bytes(canonical_json_bytes({"path": relative}) + b"\n")
        entries.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    return entries


def write_manifest(root: Path, *, entries: list[dict[str, str]], commands: tuple[str, ...]) -> Path:
    """Write one canonical manifest fixture."""
    manifest = root / "artifacts/release/evidence-manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "source_commit_sha": git(root, "rev-parse", "HEAD"),
        "release_commit_sha": git(root, "rev-parse", "HEAD"),
        "source_tree_sha": git(root, "rev-parse", "HEAD^{tree}"),
        "component_runtime_tree_hashes": {
            "api": api_runtime_hash(root),
            "ui": frontend_build_tree.current_runtime_hash(root),
        },
        "required_artifacts": list(REQUIRED_ARTIFACTS),
        "generator_commands": list(commands),
        "artifacts": entries,
    }
    parsed = JSON_VALUE_ADAPTER.validate_python(payload)
    _ = manifest.write_bytes(canonical_json_bytes(parsed) + b"\n")
    return manifest


def dirty_readme(root: Path) -> None:
    """Create one unstaged source edit."""
    _ = (root / "README.md").write_text("dirty\n", encoding="utf-8")


def untracked_file(root: Path) -> None:
    """Create one untracked source file."""
    _ = (root / "untracked.txt").write_text("new\n", encoding="utf-8")


def staged_readme(root: Path) -> None:
    """Create one staged source edit."""
    dirty_readme(root)
    _ = subprocess.run(["git", "add", "README.md"], cwd=root, check=True)


def renamed_readme(root: Path) -> None:
    """Create one staged source rename."""
    _ = subprocess.run(["git", "mv", "README.md", "RENAMED.md"], cwd=root, check=True)


def build_info_bytes(source: str) -> bytes:
    """Return one canonical build-info fixture."""
    payload = {
        "release_commit_sha": source,
        "runtime_source_commit_sha": source,
        "schema_version": "1.0",
    }
    return canonical_json_bytes(JSON_VALUE_ADAPTER.validate_python(payload)) + b"\n"


def normalized_release_command(text: str) -> str:
    """Reduce one generated command to its stable assertion shape."""
    return text.rsplit(" python ", maxsplit=1)[-1].split(" --out ", maxsplit=1)[0]


@dataclass(slots=True)
class ReleaseOrderingFixture:
    """Stateful fake command runner for the release generation transaction."""

    root: Path
    source: str
    source_mcp: bytes = b'{"source":"mcp"}\n'
    commands: list[str] = field(default_factory=list)
    installs: list[tuple[str, ...]] = field(default_factory=list)

    @property
    def mcp(self) -> Path:
        return self.root / "artifacts/contracts/mcp-tools.json"

    @property
    def build_info(self) -> Path:
        return self.root / "frontend/public/build-info.json"

    @property
    def new_build_info(self) -> bytes:
        return build_info_bytes(self.source)

    def seed_source_snapshot(self) -> None:
        """Commit source A with a tracked MCP snapshot and prior eval5."""
        self.mcp.parent.mkdir(parents=True, exist_ok=True)
        _ = self.mcp.write_bytes(self.source_mcp)
        for relative in generator.EVAL_FILES:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            _ = path.write_text("old-eval\n", encoding="utf-8")
        _ = git(self.root, "add", "artifacts/contracts/mcp-tools.json", "artifacts/eval")
        _ = git(self.root, "commit", "--quiet", "-m", "source generated snapshot")
        self.source = git(self.root, "rev-parse", "HEAD")

    def run(self, repo: Path, command: generator.Command) -> None:
        assert repo == self.root
        text = " ".join(command)
        self.commands.append(text)
        if "generate_frontend_build_info.py" in text:
            self.handle_build_info()
        elif "scripts/run_benchmark.py" in text:
            self.handle_benchmark()
        elif "scripts/export_schemas.py" in text:
            pass
        elif "telco_twin.api.openapi_contract" in text:
            self.handle_openapi()
        elif "scripts/export_mcp_tools.py" in text:
            self.handle_mcp()
        elif "scripts/probe_stack.py" in text:
            self.handle_probe(command)
        elif "scripts/generate_sbom.sh" in text:
            self.handle_sbom(command)
        else:
            message = f"unexpected command:{text}"
            raise AssertionError(message)

    def handle_build_info(self) -> None:
        assert len(self.commands) == 1
        assert not (self.root / "artifacts/contracts/openapi.json").exists()
        assert self.mcp.read_bytes() == self.source_mcp
        self.build_info.parent.mkdir(parents=True, exist_ok=True)
        _ = self.build_info.write_bytes(self.new_build_info)

    def handle_benchmark(self) -> None:
        expected_build_info = (
            "scripts/generate_frontend_build_info.py --root . "
            f"--source-commit-sha {self.source} --release-commit-sha {self.source}"
        )
        assert self.commands[0].endswith(expected_build_info)
        assert not (self.root / "artifacts/eval").exists()
        for relative in generator.EVAL_FILES:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            _ = path.write_text(f"new:{relative}\n", encoding="utf-8")

    def handle_openapi(self) -> None:
        openapi = self.root / "artifacts/contracts/openapi.json"
        openapi.parent.mkdir(parents=True, exist_ok=True)
        _ = openapi.write_bytes(canonical_json_bytes({"openapi": "new"}) + b"\n")

    def handle_mcp(self) -> None:
        _ = self.mcp.write_bytes(canonical_json_bytes({"mcp": "new"}) + b"\n")

    def handle_probe(self, command: generator.Command) -> None:
        assert self.installs == [("frontend/public/build-info.json",)]
        assert self.build_info.read_bytes() == self.new_build_info
        assert not (self.root / "artifacts/contracts/openapi.json").exists()
        assert self.mcp.read_bytes() == self.source_mcp
        self.write_stage_output(command, {"probe": "ok"})

    def handle_sbom(self, command: generator.Command) -> None:
        assert not self.build_info.exists()
        self.write_stage_output(command, {"sbom": "ok"})

    def write_stage_output(self, command: generator.Command, payload: dict[str, str]) -> None:
        output = Path(command[-1])
        output.parent.mkdir(parents=True, exist_ok=True)
        parsed = JSON_VALUE_ADAPTER.validate_python(payload)
        _ = output.write_bytes(canonical_json_bytes(parsed) + b"\n")


def test_release_manifest_verifies_required_artifacts_commands_and_hashes(tmp_path: Path) -> None:
    # Given: a clean fixture repository with exactly the Task 10 required artifacts.
    root = tmp_path / "repo"
    root.mkdir()
    _ = init_repo(root)
    entries = write_required_artifacts(root)
    _ = write_manifest(root, entries=entries, commands=GENERATOR_COMMANDS)

    # When: the release manifest verifier checks the fixture.
    result = run_script(VERIFY_SCRIPT, root)

    # Then: the manifest passes without rewriting any evidence.
    assert result.returncode == 0, result.stdout + result.stderr
    assert "release-evidence-valid:" in result.stdout


def test_release_manifest_rejects_missing_extra_stale_and_missing_generator(
    tmp_path: Path,
) -> None:
    # Given: a manifest with one extra artifact and one missing generator command.
    root = tmp_path / "repo"
    root.mkdir()
    _ = init_repo(root)
    entries = write_required_artifacts(root)
    extra = root / "artifacts/extra.json"
    extra.parent.mkdir(parents=True, exist_ok=True)
    _ = extra.write_text("{}\n", encoding="utf-8")
    entries.append(
        {
            "path": "artifacts/extra.json",
            "sha256": hashlib.sha256(b"{}\n").hexdigest(),
        }
    )
    _ = write_manifest(root, entries=entries, commands=GENERATOR_COMMANDS[:-1])

    # When: the release manifest verifier checks the malformed manifest.
    result = run_script(VERIFY_SCRIPT, root)

    # Then: the exact required set and generator command contract fail closed.
    assert result.returncode == 1
    assert "release-evidence-drift:" in result.stdout


@pytest.mark.parametrize(
    ("kind", "setup"),
    [
        ("dirty-source", dirty_readme),
        ("untracked", untracked_file),
        ("staged", staged_readme),
        ("rename", renamed_readme),
    ],
)
def test_release_manifest_rejects_dirty_staged_untracked_and_rename_source(
    tmp_path: Path,
    kind: str,
    setup: Callable[[Path], None],
) -> None:
    # Given: a valid manifest in a repository with an unrelated source edit.
    root = tmp_path / "repo"
    root.mkdir()
    _ = init_repo(root)
    entries = write_required_artifacts(root)
    manifest = write_manifest(root, entries=entries, commands=GENERATOR_COMMANDS)
    before = manifest.read_bytes()
    _ = kind
    setup(root)

    # When: the release manifest verifier checks the dirty source tree.
    with pytest.raises(verifier.ReleaseManifestError) as error:
        verifier.verify(root, manifest.relative_to(root), git(root, "rev-parse", "HEAD"))

    # Then: dirty source fails and the checked manifest is not rewritten.
    assert "dirty-source" in str(error.value)
    assert manifest.read_bytes() == before


def test_release_manifest_rejects_source_tree_mismatch(tmp_path: Path) -> None:
    # Given: a valid manifest whose source tree field is forged.
    root = tmp_path / "repo"
    root.mkdir()
    _ = init_repo(root)
    entries = write_required_artifacts(root)
    manifest = write_manifest(root, entries=entries, commands=GENERATOR_COMMANDS)
    payload = JSON_VALUE_ADAPTER.validate_json(manifest.read_bytes())
    assert isinstance(payload, dict)
    payload["source_tree_sha"] = "0" * 40
    _ = manifest.write_bytes(
        canonical_json_bytes(JSON_VALUE_ADAPTER.validate_python(payload)) + b"\n"
    )

    # When: the verifier checks the forged identity.
    with pytest.raises(verifier.ReleaseManifestError) as error:
        verifier.verify(root, manifest.relative_to(root), git(root, "rev-parse", "HEAD"))

    # Then: source/tree mismatch is rejected before release claims are trusted.
    assert "source-tree-mismatch" in str(error.value)


def test_release_generator_command_failure_restores_original_generated_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: a clean source checkout with an existing generated artifact.
    root = tmp_path / "repo"
    root.mkdir()
    _ = init_repo(root)
    target = root / "artifacts/contracts/mcp-tools.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    original = b'{"old":true}\n'
    _ = target.write_bytes(original)
    _ = git(root, "add", "artifacts/contracts/mcp-tools.json")
    _ = git(root, "commit", "--quiet", "-m", "generated fixture")
    source = git(root, "rev-parse", "HEAD")

    def fail_after_mutation(repo: Path, command: generator.Command) -> None:
        _ = repo
        _ = command
        _ = target.write_bytes(b"partial\n")
        raise subprocess.CalledProcessError(17, command)

    monkeypatch.setattr(generator, "_run", fail_after_mutation)

    # When: generation fails after mutating an output path.
    with pytest.raises(subprocess.CalledProcessError):
        _ = generator.generate(root, source)

    # Then: the original bytes are restored.
    assert target.read_bytes() == original


def test_release_generator_build_info_first_and_recreates_existing_eval5(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: source A already tracks the canonical current MCP snapshot and prior eval5.
    root = tmp_path / "repo"
    root.mkdir()
    _ = init_repo(root)
    fixture = ReleaseOrderingFixture(root=root, source="")
    fixture.seed_source_snapshot()
    original_install = cast(
        "Callable[[Path, Path, tuple[str, ...]], None]",
        vars(generator)["_install_stage_files"],
    )

    def recording_install(repo: Path, stage: Path, relatives: tuple[str, ...]) -> None:
        fixture.installs.append(relatives)
        original_install(repo, stage, relatives)

    monkeypatch.setattr(generator, "_run", fixture.run)
    monkeypatch.setattr(generator, "_install_stage_files", recording_install)

    # When: generation runs transactionally from the clean source snapshot.
    manifest = generator.generate(root, fixture.source)

    # Then: build-info precedes benchmark/contracts, existing eval dir was removed,
    # and contracts are not installed until final publish.
    assert manifest.is_file()
    assert [normalized_release_command(item) for item in fixture.commands] == [
        (
            "scripts/generate_frontend_build_info.py --root . "
            f"--source-commit-sha {fixture.source} --release-commit-sha {fixture.source}"
        ),
        (
            "scripts/run_benchmark.py --split heldout --safety-set "
            "backend/fixtures/eval/safety-v1.jsonl --seed 20270827"
        ),
        "scripts/export_schemas.py",
        "-m telco_twin.api.openapi_contract",
        "scripts/export_mcp_tools.py",
        "scripts/probe_stack.py",
        "bash scripts/generate_sbom.sh --repo-root .",
    ]
    assert fixture.installs[0] == ("frontend/public/build-info.json",)
    assert fixture.installs[-1] == generator.REQUIRED_ARTIFACTS
    assert generator.REQUIRED_ARTIFACTS[0:2] not in fixture.installs[:-1]
    assert (
        (root / "artifacts/eval/counterfactual.json").read_text(encoding="utf-8").startswith("new:")
    )


def test_release_generator_declares_full_deterministic_command_contract() -> None:
    # Given/When: the generator command contract is read as data.
    joined = "\n".join(generator.GENERATOR_COMMANDS)
    source = GENERATE_SCRIPT.read_text(encoding="utf-8")

    # Then: it invokes benchmark, build-info write, Compose probe, and SBOM only.
    assert generator.GENERATOR_COMMANDS[0].startswith(
        "uv run --project backend python scripts/generate_frontend_build_info.py"
    )
    assert joined.index("scripts/generate_frontend_build_info.py") < joined.index(
        "scripts/run_benchmark.py"
    )
    assert joined.index("scripts/run_benchmark.py") < joined.index("scripts/export_schemas.py")
    assert "scripts/run_benchmark.py --split heldout" in joined
    assert "scripts/generate_frontend_build_info.py --root ." in joined
    assert "scripts/with_compose_cleanup.sh -f docker-compose.yml" in joined
    assert "scripts/probe_stack.py --out {probe_out}" in joined
    assert "bash scripts/generate_sbom.sh --repo-root . --out {sbom_out}" in joined
    assert "artifacts/contracts/mcp-tools.json" in generator.REQUIRED_ARTIFACTS
    assert "artifacts/probe/local-stack-probe.json" in generator.REQUIRED_ARTIFACTS
    assert "artifacts/security/component-inventory.json" in generator.REQUIRED_ARTIFACTS
    assert "_require_prior_eval_dir_clean(root)" in source
    assert "_remove_eval_dir(root)" in source
    assert "deployment_preflight" not in source
