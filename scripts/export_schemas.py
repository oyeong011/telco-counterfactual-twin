#!/usr/bin/env -S uv run --project backend python
"""Export and validate deterministic JSON Schemas from Pydantic contracts.

Run with `uv run --project backend python scripts/export_schemas.py --check`.
"""

import typer
from telco_twin.schema_export import main

if __name__ == "__main__":
    typer.run(main)
