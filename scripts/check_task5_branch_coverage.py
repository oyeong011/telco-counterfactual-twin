# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["pydantic==2.13.4"]
# ///
# ─── How to run ───
# uv run --project backend python scripts/check_task5_branch_coverage.py coverage.json
"""Require true branch coverage for every Task5 package."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar, Final

from pydantic import BaseModel, ConfigDict, ValidationError

PACKAGES: Final = ("approval", "counterfactual", "safety", "state")
MINIMUM_PERCENT: Final = 90.0


class _CoverageModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)


class _Summary(_CoverageModel):
    covered_branches: int
    num_branches: int


class _FileCoverage(_CoverageModel):
    summary: _Summary


class _CoverageReport(_CoverageModel):
    files: dict[str, _FileCoverage]


def _package_percent(report: _CoverageReport, package: str) -> float:
    rows = tuple(
        value.summary for path, value in report.files.items() if f"/{package}/" in path
    )
    covered = sum(row.covered_branches for row in rows)
    branches = sum(row.num_branches for row in rows)
    return 0.0 if not rows or branches == 0 else covered / branches * 100


def main(arguments: Sequence[str]) -> int:
    """Print per-package percentages and fail if any is below ninety."""
    if len(arguments) != 1:
        print("usage: check_task5_branch_coverage.py COVERAGE_JSON", file=sys.stderr)
        return 2
    try:
        report = _CoverageReport.model_validate_json(Path(arguments[0]).read_bytes())
    except (OSError, ValidationError) as error:
        print(f"task5_branch_coverage=input-error:{type(error).__name__}")
        return 2
    percentages = tuple(
        (package, _package_percent(report, package)) for package in PACKAGES
    )
    passed = all(percent >= MINIMUM_PERCENT for _, percent in percentages)
    details = " ".join(f"{package}={percent:.2f}%" for package, percent in percentages)
    result = "pass" if passed else "fail"
    print(f"task5_branch_coverage={result} {details}")
    return int(not passed)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
