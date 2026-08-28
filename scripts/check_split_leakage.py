#!/usr/bin/env -S uv run --project backend python
# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = []
# ///

# ─── How to run ───
# 1. Install uv (if not installed):
#      curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Run through the pinned project:
#      uv run --project backend python scripts/check_split_leakage.py --help
# 3. Or make executable and run:
#      chmod +x scripts/check_split_leakage.py && ./scripts/check_split_leakage.py --help
# ──────────────────

"""Validate immutable diagnosis/safety denominators and split disjointness."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, override

import typer
from telco_twin.domain.scenario import FaultFamily
from telco_twin.eval.metrics import SAFETY_COUNT, SafetyExpectation
from telco_twin.eval.rules_baseline import (
    EvaluationDataError,
    load_diagnosis_dataset,
    load_safety_cases,
)


@dataclass(frozen=True, slots=True)
class CountArgumentError(Exception):
    """A denominator option did not name the exact two frozen splits."""

    value: str

    @override
    def __str__(self) -> str:
        return f"invalid-count-option: {self.value}"


def _counts(value: str) -> tuple[int, int]:
    parts = value.split(",")
    if len(parts) != 2:
        raise CountArgumentError(value)
    parsed: dict[str, int] = {}
    for part in parts:
        key, separator, raw = part.partition("=")
        if not separator or key not in {"development", "heldout"}:
            raise CountArgumentError(value)
        try:
            parsed[key] = int(raw)
        except ValueError as error:
            raise CountArgumentError(value) from error
    if set(parsed) != {"development", "heldout"}:
        raise CountArgumentError(value)
    return parsed["development"], parsed["heldout"]


def main(
    splits_path: Path,
    safety_path: Path,
    expect_total: Annotated[int, typer.Option()],
    expect_splits: Annotated[str, typer.Option()],
    expect_each_fault: Annotated[str, typer.Option()],
) -> None:
    """Check exact v1 counts, per-family balance, hashes, and safety membership."""
    try:
        dataset = load_diagnosis_dataset(splits_path.parent)
        if splits_path.name != "splits-v1.json":
            raise EvaluationDataError(splits_path, "expected the v1 split manifest")
        safety = load_safety_cases(safety_path)
        development_count, heldout_count = _counts(expect_splits)
        development_each, heldout_each = _counts(expect_each_fault)
        observed_total = len(dataset.cases)
        if observed_total != expect_total:
            raise CountArgumentError(
                f"expected total={expect_total}, observed={observed_total}"
            )
        if (len(dataset.splits.development), len(dataset.splits.heldout)) != (
            development_count,
            heldout_count,
        ):
            raise CountArgumentError(expect_splits)
        development_counts = tuple(
            sum(member.fault_family is family for member in dataset.splits.development)
            for family in FaultFamily
        )
        heldout_counts = tuple(
            sum(member.fault_family is family for member in dataset.splits.heldout)
            for family in FaultFamily
        )
        if set(development_counts) != {development_each} or set(heldout_counts) != {
            heldout_each
        }:
            raise CountArgumentError(expect_each_fault)
        safe = sum(case.expectation is SafetyExpectation.SAFE for case in safety)
        unsafe = sum(case.expectation is SafetyExpectation.UNSAFE for case in safety)
        if (safe, unsafe) != (SAFETY_COUNT, SAFETY_COUNT):
            raise CountArgumentError(f"safety safe={safe},unsafe={unsafe}")
    except (CountArgumentError, EvaluationDataError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error
    typer.echo(
        " ".join(
            (
                f"split-check: PASS total={observed_total}",
                f"development={development_count}",
                f"heldout={heldout_count}",
                f"safe={safe}",
                f"unsafe={unsafe}",
            )
        )
    )


if __name__ == "__main__":
    typer.run(main)
