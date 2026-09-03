#!/usr/bin/env -S uv run --project backend python
# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["rfc8785>=0.1.4,<0.2", "typer>=0.21,<1"]
# ///

# ─── How to run ───
# 1. Generate:
#      uv run --project backend python scripts/export_mcp_tools.py
# 2. Check:
#      uv run --project backend python scripts/export_mcp_tools.py --check
# ──────────────────

"""Export or check the canonical MCP tools artifact."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Annotated

import typer
from telco_twin.domain.canonical import JSON_VALUE_ADAPTER, canonical_json_bytes
from telco_twin.mcp.contracts import tool_manifest

DEFAULT_OUTPUT = Path("artifacts/contracts/mcp-tools.json")


def _canonical_tools() -> bytes:
    """Return the production MCP tool manifest as canonical JSON bytes."""
    manifest = JSON_VALUE_ADAPTER.validate_python(tool_manifest())
    return canonical_json_bytes(manifest) + b"\n"


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


def main(
    out: Annotated[Path, typer.Option("--out")] = DEFAULT_OUTPUT,
    check: Annotated[bool, typer.Option("--check")] = False,
) -> None:
    """Write or validate artifacts/contracts/mcp-tools.json."""
    expected = _canonical_tools()
    if check:
        if not out.is_file() or out.read_bytes() != expected:
            typer.echo(f"mcp-tools-drift:{out}")
            raise typer.Exit(code=1)
        typer.echo(f"mcp-tools-valid:{out}")
        return
    _atomic_write(out, expected)
    typer.echo(f"mcp-tools-written:{out}")


if __name__ == "__main__":
    typer.run(main)
