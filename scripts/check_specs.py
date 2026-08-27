#!/usr/bin/env -S uv run --project backend python
"""Check that the contract-first bootstrap has every required specification."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Final

import typer

REQUIRED_MARKDOWN: Final = (
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
DEFAULT_ROOT: Final = Path(".")


def main(
    root: Annotated[
        Path, typer.Option("--root", exists=True, file_okay=False)
    ] = DEFAULT_ROOT,
) -> None:
    """Validate file presence and minimum machine-reviewable Markdown structure."""
    errors: list[str] = []
    for relative_path in REQUIRED_MARKDOWN:
        path = root / relative_path
        if not path.is_file():
            errors.append(f"missing-required-file:{relative_path}")
            continue
        text = path.read_text(encoding="utf-8")
        if not text.startswith("# ") or "\n## " not in text:
            errors.append(f"invalid-markdown-structure:{relative_path}")
    schemas = root / "specs" / "schemas"
    if not schemas.is_dir() or not any(path.is_file() for path in schemas.iterdir()):
        errors.append("missing-schema-boundary:specs/schemas")
    if errors:
        for error in errors:
            typer.echo(error, err=True)
        raise typer.Exit(code=3)
    typer.echo("spec-contracts-valid")


if __name__ == "__main__":
    typer.run(main)
