#!/usr/bin/env -S uv run --project backend python
"""Run the secret-safe direct STS denial classifier."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, assert_never

import typer
from telco_twin.bootstrap.deny_exchange_wire import probe_deny_exchange


def main(
    provider_json: Annotated[Path, typer.Option("--provider-json")],
    provider_resource: Annotated[str, typer.Option("--provider-resource")],
    out: Annotated[Path, typer.Option("--out")],
) -> None:
    """Write only redacted classification status, codes, and evidence hashes."""
    try:
        provider_snapshot = provider_json.read_text(encoding="utf-8")
    except OSError:
        typer.echo("deny-exchange-rejection-unproven", err=True)
        raise typer.Exit(code=3) from None
    classification = probe_deny_exchange(provider_snapshot, provider_resource)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        _ = out.write_text(
            classification.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        typer.echo("deny-classification-write-failed", err=True)
        raise typer.Exit(code=3) from None
    typer.echo(classification.status)
    match classification.status:
        case "deny-rejected":
            return
        case "deny-exchange-rejection-unproven" | "deny-exchange-unexpected-success":
            raise typer.Exit(code=3)
        case _:
            assert_never(classification.status)


if __name__ == "__main__":
    typer.run(main)
