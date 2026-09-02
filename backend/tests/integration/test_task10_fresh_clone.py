"""Bounded fresh-clone checks for the Task 10 proof contract."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT: Final = Path(__file__).resolve().parents[3]
OWNED_FILES: Final = (
    Path("Makefile"),
    Path(".github/workflows/ci.yml"),
    Path(".github/workflows/release-candidate.yml"),
    Path(".env.example"),
    Path(".gitignore"),
    Path("backend/tests/integration/test_task10_ci_contract.py"),
    Path("backend/tests/integration/test_task10_fresh_clone.py"),
)
TASK10_CONTRACT_FILES: Final = (
    Path("scripts/export_mcp_tools.py"),
    Path("scripts/generate_sbom.sh"),
    Path("scripts/probe_stack.py"),
    Path("scripts/verify_release_manifest.py"),
    Path("artifacts/security/component-inventory.json"),
)
MAKE_TARGETS: Final = (
    "bootstrap",
    "verify",
    "security",
    "probe",
    "generate-release-evidence",
)


def run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run Git with bounded output for fixture setup."""
    return subprocess.run(
        ("git", *args),
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def run_command(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a bounded fixture command."""
    return subprocess.run(
        args,
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.skipif(
    not (REPO_ROOT / ".git").exists(),
    reason="fresh-clone contract requires a Git checkout",
)
def test_task10_contract_survives_bounded_fresh_clone_acceptance_seam(
    tmp_path: Path,
) -> None:
    # Given: a fresh clone of HEAD overlaid with the current Task 10 contract files.
    clone = tmp_path / "clone"
    result = run_git(tmp_path, "clone", "--quiet", "--no-hardlinks", str(REPO_ROOT), str(clone))
    assert result.returncode == 0, result.stderr
    for relative in (*OWNED_FILES, *TASK10_CONTRACT_FILES):
        source = REPO_ROOT / relative
        destination = clone / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_file():
            _ = shutil.copy2(source, destination)

    # When: Make resolves Task 10 targets in dry-run mode inside the clone.
    make = subprocess.run(
        ("make", "--dry-run", *MAKE_TARGETS),
        cwd=clone,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    # Then: the contract is inspectable without invoking pytest or recursing into itself.
    assert make.returncode == 0, make.stdout + make.stderr
    assert "pytest backend/tests/integration/test_task10_fresh_clone.py" not in make.stdout
    assert "uv sync --project backend --locked --all-groups" in make.stdout
    assert "pnpm --dir frontend install --frozen-lockfile" in make.stdout
    assert "scripts/probe_stack.py --out artifacts/probe/local-stack-probe.json" in make.stdout
    assert (clone / ".env.example").is_file()
    assert run_git(clone, "check-ignore", ".env.example").returncode == 1

    # When: the clone executes bounded Task 10 security/generation seams.
    if sys.platform == "linux":
        sbom = run_command(clone, "make", "sbom-check")
    else:
        sbom = run_command(clone, "bash", "-n", "scripts/generate_sbom.sh")
        assert (clone / "artifacts/security/component-inventory.json").is_file()
    generation = run_command(clone, "make", "--dry-run", "generate-release-evidence")
    contracts = run_command(
        clone,
        "uv",
        "run",
        "--project",
        "backend",
        "pytest",
        "backend/tests/integration/test_task10_ci_contract.py",
        "-q",
    )

    # Then: the copied Task 10 files are executable without the recursive full suite.
    assert sbom.returncode == 0, sbom.stdout + sbom.stderr
    assert generation.returncode == 0, generation.stdout + generation.stderr
    assert "scripts/generate_release_evidence.py" in generation.stdout
    assert contracts.returncode == 0, contracts.stdout + contracts.stderr
