#!/usr/bin/env -S uv run --project backend python
# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["pydantic==2.13.4", "rfc8785>=0.1.4,<0.2", "typer>=0.21,<1"]
# ///

# ─── How to run ───
# 1. Install uv (if not installed):
#      curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Run directly (no venv, no pip install needed):
#      uv run generate_frontend_build_info.py [ARGS]
# 3. Or make executable and run:
#      chmod +x generate_frontend_build_info.py && ./generate_frontend_build_info.py
# ──────────────────

"""Generate/check static UI identity with a source-A/generated-B contract.

Run generation on clean source commit A, then commit this output as B. The
generated file is excluded from runtime and asset records, so it cannot hash
itself. By default both commit fields identify A; release automation may pass
an ancestor release SHA explicitly when A and the release identity differ.
"""

import sys
from pathlib import Path

import typer

if not __package__:
    sys.path[0:0] = [str(Path(__file__).resolve().parents[1])]

from scripts.frontend_build_identity import main

if __name__ == "__main__":
    typer.run(main)
