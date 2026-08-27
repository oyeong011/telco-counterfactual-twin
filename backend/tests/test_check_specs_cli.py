from __future__ import annotations

from typing import TYPE_CHECKING

from .conftest import run_project_script

if TYPE_CHECKING:
    from pathlib import Path

REQUIRED_MARKDOWN = (
    "specs/prd.md",
    "specs/test-spec.md",
    "specs/threat-model.md",
    "specs/api-contract.md",
    "docs/plans/2026-08-27-telco-counterfactual-twin-design.md",
    "docs/adr/0001-deterministic-simulator.md",
    "docs/adr/0002-no-mutation-authority.md",
    "docs/adr/0003-sse-progress.md",
    "docs/adr/0004-deployment-rollback.md",
    "docs/adr/0005-runtime-claim-map.md",
    "docs/adr/0006-mcp-2025-06-18.md",
)


def write_complete_spec_fixture(root: Path) -> None:
    """Write the smallest structurally complete spec tree."""
    for relative_path in REQUIRED_MARKDOWN:
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        _ = target.write_text(
            "# Contract\n\n## Status\nAccepted\n\n## Decision\nNo network mutation authority.\n",
            encoding="utf-8",
        )
    schemas = root / "specs" / "schemas"
    schemas.mkdir(parents=True, exist_ok=True)
    _ = (schemas / "README.md").write_text("# Schemas\n\nReserved for Todo 2.\n", encoding="utf-8")


def test_accepts_complete_spec_tree_when_every_contract_is_present(tmp_path: Path) -> None:
    # Given
    write_complete_spec_fixture(tmp_path)

    # When
    result = run_project_script("check_specs.py", "--root", str(tmp_path))

    # Then
    assert result.returncode == 0, result.stderr


def test_rejects_spec_tree_when_required_adr_is_missing(tmp_path: Path) -> None:
    # Given
    write_complete_spec_fixture(tmp_path)
    (tmp_path / "docs" / "adr" / "0002-no-mutation-authority.md").unlink()

    # When
    result = run_project_script("check_specs.py", "--root", str(tmp_path))

    # Then
    assert result.returncode == 3
    assert "missing-required-file" in result.stderr
