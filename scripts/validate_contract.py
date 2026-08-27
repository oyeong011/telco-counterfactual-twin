#!/usr/bin/env -S uv run --project backend python
"""Validate one JSON contract with the normative project validator.

Run with `uv run --project backend python scripts/validate_contract.py --help`.
"""

import typer
from telco_twin.contract_validation import main

if __name__ == "__main__":
    typer.run(main)
