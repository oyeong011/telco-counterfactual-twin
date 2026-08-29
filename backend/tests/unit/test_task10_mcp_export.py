"""Task 10 MCP tool export CLI contracts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Final

from telco_twin.domain.canonical import JSON_VALUE_ADAPTER, canonical_json_bytes
from telco_twin.mcp.contracts import tool_manifest

REPO_ROOT: Final = Path(__file__).resolve().parents[3]
SCRIPT: Final = REPO_ROOT / "scripts/export_mcp_tools.py"


def run_export(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the export CLI against the checkout under test."""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join((str(REPO_ROOT / "backend/src"), str(REPO_ROOT)))
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )


def test_mcp_tools_export_uses_production_manifest_and_canonical_bytes(tmp_path: Path) -> None:
    # Given: a requested MCP tools artifact outside the repository tree.
    output = tmp_path / "mcp-tools.json"

    # When: the export CLI writes the artifact.
    result = run_export("--out", str(output))

    # Then: bytes are the RFC8785 canonical production tool manifest plus newline.
    assert result.returncode == 0, result.stdout + result.stderr
    manifest = JSON_VALUE_ADAPTER.validate_python(tool_manifest())
    assert output.read_bytes() == canonical_json_bytes(manifest) + b"\n"
    assert json.loads(output.read_text(encoding="utf-8"))["tools"]


def test_mcp_tools_check_detects_stale_artifact_without_rewriting(tmp_path: Path) -> None:
    # Given: an exported artifact that is later overwritten with stale bytes.
    output = tmp_path / "mcp-tools.json"
    assert run_export("--out", str(output)).returncode == 0
    stale = b"{}\n"
    _ = output.write_bytes(stale)

    # When: the check mode validates the stale artifact.
    result = run_export("--out", str(output), "--check")

    # Then: drift is reported and the stale bytes remain untouched.
    assert result.returncode == 1
    assert "mcp-tools-drift:" in result.stdout
    assert output.read_bytes() == stale
