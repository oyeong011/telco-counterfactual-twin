"""Explicit per-package Task5 branch-coverage gate tests."""

import json
import subprocess
import sys
from pathlib import Path
from typing import TypedDict

REPO_ROOT = Path(__file__).resolve().parents[3]
GATE = REPO_ROOT / "scripts/check_task5_branch_coverage.py"


class _Summary(TypedDict):
    covered_branches: int
    num_branches: int


class _FileCoverage(TypedDict):
    summary: _Summary


class _CoverageReport(TypedDict):
    files: dict[str, _FileCoverage]


def _report(state_covered: int) -> _CoverageReport:
    files: dict[str, _FileCoverage] = {}
    for package in ("approval", "counterfactual", "safety"):
        files[f"backend/src/telco_twin/{package}/module.py"] = {
            "summary": {"covered_branches": 9, "num_branches": 10}
        }
    files["backend/src/telco_twin/state/module.py"] = {
        "summary": {"covered_branches": state_covered, "num_branches": 10}
    }
    return {"files": files}


def _run(report: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GATE), str(report)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_coverage_gate_accepts_each_task5_package_at_ninety_percent(
    tmp_path: Path,
) -> None:
    report = tmp_path / "coverage-pass.json"
    _ = report.write_text(json.dumps(_report(9)), encoding="utf-8")
    result = _run(report)
    assert result.returncode == 0
    assert "task5_branch_coverage=pass" in result.stdout


def test_coverage_gate_rejects_any_task5_package_below_ninety_percent(
    tmp_path: Path,
) -> None:
    report = tmp_path / "coverage-fail.json"
    _ = report.write_text(json.dumps(_report(8)), encoding="utf-8")
    result = _run(report)
    assert result.returncode == 1
    assert "state=80.00%" in result.stdout
