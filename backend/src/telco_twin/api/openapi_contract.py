"""Deterministic OpenAPI artifact generation and drift checking."""
# pyright: reportUnusedCallResult=false

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Final

import typer

from telco_twin.api.app import create_app
from telco_twin.api.build_identity import repository_root
from telco_twin.api.settings import ApiSettings

ARTIFACT_RELATIVE_PATH: Final = Path("artifacts/contracts/openapi.json")


def openapi_bytes() -> bytes:
    """Return stable UTF-8 OpenAPI bytes from the production application factory."""
    schema = create_app(ApiSettings()).openapi()
    return (
        json.dumps(schema, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()


def artifact_path() -> Path:
    """Return the repository-owned generated contract location."""
    return repository_root() / ARTIFACT_RELATIVE_PATH


def check_openapi() -> bool:
    """Return whether the committed artifact exactly matches current routes/models."""
    path = artifact_path()
    return path.is_file() and path.read_bytes() == openapi_bytes()


def main(
    *,
    check: Annotated[
        bool,
        typer.Option(help="Fail if the artifact has drifted."),
    ] = False,
) -> None:
    """Write or verify the canonical OpenAPI contract artifact."""
    path = artifact_path()
    if check:
        if not check_openapi():
            raise typer.Exit(code=1)
        typer.echo(f"openapi-check=ok path={ARTIFACT_RELATIVE_PATH.as_posix()}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(openapi_bytes())
    typer.echo(f"openapi-written={path.stat().st_size} path={ARTIFACT_RELATIVE_PATH.as_posix()}")


if __name__ == "__main__":
    typer.run(main)
