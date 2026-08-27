"""Isolated clean Git checkout helpers for real probe CLI tests."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Final

REPO_ROOT: Final = Path(__file__).resolve().parents[3]
PROBE_OVERLAY: Final = (
    Path("backend/src/telco_twin/state/probe_evidence.py"),
    Path("scripts/task5_probe_provenance.py"),
    Path("scripts/task5_safety_probe.py"),
)


def clean_probe_checkout(parent: Path) -> Path:
    """Clone committed HEAD, overlay current probe code, and commit a clean fixture."""
    checkout = parent / "probe-checkout"
    _ = subprocess.run(
        ["git", "clone", "--quiet", "--no-hardlinks", str(REPO_ROOT), str(checkout)],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    for relative in PROBE_OVERLAY:
        _ = shutil.copy2(REPO_ROOT / relative, checkout / relative)
    for key, value in (("user.name", "Task5 Test"), ("user.email", "task5@example.invalid")):
        _ = subprocess.run(
            ["git", "config", key, value],
            cwd=checkout,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    _ = subprocess.run(
        ["git", "add", *(str(path) for path in PROBE_OVERLAY)],
        cwd=checkout,
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    _ = subprocess.run(
        ["git", "commit", "--quiet", "--allow-empty", "-m", "probe fixture"],
        cwd=checkout,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return checkout


def checkout_head(checkout: Path) -> str:
    """Return one isolated fixture's full committed SHA."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=checkout,
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    return result.stdout.strip()


def run_probe(checkout: Path, output: Path) -> subprocess.CompletedProcess[str]:
    """Run the checkout's real probe with imports pinned to that checkout."""
    return subprocess.run(
        [sys.executable, "-m", "scripts.task5_safety_probe", "--out", str(output)],
        cwd=checkout,
        env=_checkout_environment(checkout),
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )


def _checkout_environment(checkout: Path) -> dict[str, str]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join((str(checkout / "backend/src"), str(checkout)))
    return environment


def run_local_validation(
    checkout: Path,
    artifact: Path,
) -> subprocess.CompletedProcess[str]:
    """Validate one artifact against the checkout's live HEAD and status."""
    source = (
        "import sys\n"
        "from pathlib import Path\n"
        "from scripts.task5_probe_provenance import "
        "validate_local_probe_artifact_json\n"
        "result = validate_local_probe_artifact_json("
        "Path(sys.argv[1]).read_text(encoding='utf-8'), Path.cwd())\n"
        "print(result.artifact_hash)\n"
    )
    return subprocess.run(
        [sys.executable, "-c", source, str(artifact)],
        cwd=checkout,
        env=_checkout_environment(checkout),
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
