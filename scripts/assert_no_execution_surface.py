# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["pydantic==2.13.4"]
# ///
# ─── How to run ───
# uv run --project backend python scripts/assert_no_execution_surface.py specs/schemas backend/src
"""Reject mutation and process-execution capabilities in explicit roots."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.execution_surface_scan import scan_paths
from scripts.execution_surface_types import MutationSurface

__all__ = ("MutationSurface", "scan_paths")


def main(arguments: Sequence[str]) -> int:
    """Print stable scanner evidence and fail on findings or absent roots."""
    if not arguments:
        print("usage: assert_no_execution_surface.py PATH [PATH ...]", file=sys.stderr)
        return 2
    findings = scan_paths(tuple(Path(argument) for argument in arguments))
    for finding in findings:
        print(f"{finding.path}:{finding.line}:{finding.kind}:{finding.name}")
    print(f"mutation_surfaces={len(findings)}")
    return int(bool(findings))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
