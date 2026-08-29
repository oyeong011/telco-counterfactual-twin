from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Final, TypedDict

from pydantic import TypeAdapter

REPO_ROOT = Path(__file__).resolve().parents[3]
SBOM_SCRIPT = REPO_ROOT / "scripts/generate_sbom.sh"
EXPECTED_NOTICE: Final = (
    "Deterministic component inventory from pinned lock sources only; not a vulnerability scan."
)


class SbomArtifact(TypedDict):
    path: str


class SbomManifest(TypedDict):
    schema_version: str
    notice: str
    artifacts: list[SbomArtifact]


SBOM_MANIFEST_ADAPTER: Final[TypeAdapter[SbomManifest]] = TypeAdapter(SbomManifest)


def run_sbom(
    out_path: Path,
    *,
    check: bool = False,
    repo_root: Path = REPO_ROOT,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command = ["bash", str(SBOM_SCRIPT), "--repo-root", str(repo_root), "--out", str(out_path)]
    if check:
        command.append("--check")
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
        env=env,
    )


def _bsd_tool_env(tmp_path: Path) -> dict[str, str]:
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    tool_targets = {
        "python3": Path(sys.executable),
        "jq": Path(shutil.which("jq") or ""),
        "shasum": Path(shutil.which("shasum") or ""),
    }
    for name, target in tool_targets.items():
        if not target.exists():
            message = f"required tool missing for test: {name}"
            raise AssertionError(message)
        (shim_dir / name).symlink_to(target)
    return {"PATH": f"{shim_dir}:/usr/bin:/bin"}


def test_sbom_script_emits_deterministic_inventory_without_absolute_paths(
    tmp_path: Path,
) -> None:
    # Given: two fresh output locations for the same repository inputs.
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    # When: the inventory is generated twice from the pinned lock sources.
    first_result = run_sbom(first)
    second_result = run_sbom(second)
    # Then: both runs succeed, produce byte-identical manifests, and avoid absolute paths.
    assert first_result.returncode == 0, first_result.stdout + first_result.stderr
    assert second_result.returncode == 0, second_result.stdout + second_result.stderr
    assert first.read_bytes() == second.read_bytes()
    manifest = SBOM_MANIFEST_ADAPTER.validate_json(first.read_bytes())
    assert manifest["schema_version"] == "1.0"
    assert manifest["notice"] == EXPECTED_NOTICE
    assert {artifact["path"] for artifact in manifest["artifacts"]} == {
        "backend/uv.lock",
        "frontend/package.json",
        "frontend/pnpm-lock.yaml",
    }
    assert str(REPO_ROOT) not in first.read_text(encoding="utf-8")
    assert (
        hashlib.sha256(first.read_bytes()).hexdigest()
        == hashlib.sha256(second.read_bytes()).hexdigest()
    )


def test_sbom_script_fails_when_required_lockfiles_are_missing(tmp_path: Path) -> None:
    # Given: a repository root without the mandatory backend/frontend lock sources.
    repo_root = tmp_path / "repo"
    (repo_root / "backend").mkdir(parents=True)
    (repo_root / "frontend").mkdir()
    out_path = tmp_path / "missing.json"
    # When: the sbom generator is asked to inventory the incomplete repository.
    result = run_sbom(out_path, repo_root=repo_root)
    # Then: it fails closed and does not write a misleading manifest.
    assert result.returncode == 1
    assert not out_path.exists()
    assert "missing required lock source" in result.stderr


def test_sbom_script_reports_missing_runtime_tools(tmp_path: Path) -> None:
    # Given: an environment without the shell tools the script requires.
    out_path = tmp_path / "tools.json"
    stripped_env = {"PATH": "/usr/bin:/bin"}
    # When: the generator starts without its declared toolchain.
    result = run_sbom(out_path, env=stripped_env)
    # Then: it fails with a specific tool error rather than pretending to succeed.
    assert result.returncode == 1
    assert "missing required tool" in result.stderr
    assert not out_path.exists()


def test_sbom_check_mode_reports_drift_without_rewriting_bytes(tmp_path: Path) -> None:
    # Given: a previously generated manifest that has been tampered with.
    out_path = tmp_path / "component-inventory.json"
    generated = run_sbom(out_path)
    assert generated.returncode == 0, generated.stdout + generated.stderr
    stale_bytes = b'{"stale":true}\n'
    _ = out_path.write_bytes(stale_bytes)
    # When: check mode verifies the tracked file instead of rewriting it.
    result = run_sbom(out_path, check=True)
    # Then: drift is reported with a nonzero exit code and the stale file is left untouched.
    assert result.returncode == 1
    assert "sbom drift" in result.stderr
    assert out_path.read_bytes() == stale_bytes


def test_sbom_script_runs_with_bsd_mktemp_and_real_check_mode(tmp_path: Path) -> None:
    # Given: a BSD-like shell path using /usr/bin/mktemp plus shims for required modern tools.
    out_path = tmp_path / "component-inventory.json"
    bsd_env = _bsd_tool_env(tmp_path)
    # When: the script generates and then verifies the matching manifest.
    generated = run_sbom(out_path, env=bsd_env)
    verified = run_sbom(out_path, check=True, env=bsd_env)
    # Then: both modes succeed without stale rewrite and the manifest stays byte-stable.
    assert generated.returncode == 0, generated.stdout + generated.stderr
    original_bytes = out_path.read_bytes()
    assert verified.returncode == 0, verified.stdout + verified.stderr
    assert "sbom_verified=" in verified.stdout
    assert out_path.read_bytes() == original_bytes
