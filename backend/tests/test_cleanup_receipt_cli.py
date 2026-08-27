from __future__ import annotations

from typing import TYPE_CHECKING

from .conftest import run_project_script

if TYPE_CHECKING:
    from pathlib import Path


def test_rejects_interrupted_cleanup_receipt(tmp_path: Path) -> None:
    # Given
    receipt = tmp_path / "cleanup.json"
    _ = receipt.write_text(
        """{
  "cleanup_complete": false,
  "temporary_resources": ["topic:preflight-left-behind"],
  "restored_bindings": false
}
""",
        encoding="utf-8",
    )

    # When
    result = run_project_script("provision_wif.py", "--validate-cleanup", str(receipt))

    # Then
    assert result.returncode == 3
    assert "cleanup-incomplete" in result.stderr
