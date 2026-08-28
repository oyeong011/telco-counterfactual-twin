#!/usr/bin/env -S uv run --project backend python
# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["pydantic==2.13.4", "typer>=0.21,<1"]
# ///

# ─── How to run ───
# 1. Install uv (if not installed):
#      curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Run directly (no venv, no pip install needed):
#      uv run assert_visual_qa_manifest.py MANIFEST [ARGS]
# 3. Or make executable and run:
#      chmod +x assert_visual_qa_manifest.py && ./assert_visual_qa_manifest.py MANIFEST
# ───────────────────

"""Fail-closed assertion for Task 9 route/state/viewport visual evidence."""

import sys
from pathlib import Path

import typer

if not __package__:
    sys.path[0:0] = [str(Path(__file__).resolve().parents[1])]

from scripts.visual_qa_manifest import main

if __name__ == "__main__":
    typer.run(main)
