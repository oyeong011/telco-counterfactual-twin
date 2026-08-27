from __future__ import annotations

from typing import TYPE_CHECKING

from .conftest import run_project_script

if TYPE_CHECKING:
    from pathlib import Path

EXPECTED_SHA = "a" * 40
STALE_SHA = "b" * 40


def test_accepts_auth_blocked_workflow_only_at_expected_head(tmp_path: Path) -> None:
    # Given
    runs = tmp_path / "runs.json"
    logs = tmp_path / "logs.txt"
    _ = runs.write_text(
        f"""[
  {{"databaseId":11,"headSha":"{STALE_SHA}","status":"completed","conclusion":"success","createdAt":"2026-08-27T00:00:00Z","url":"https://example.invalid/11"}},
  {{"databaseId":12,"headSha":"{EXPECTED_SHA}","status":"completed","conclusion":"success","createdAt":"2026-08-27T00:01:00Z","url":"https://example.invalid/12"}}
]\n""",
        encoding="utf-8",
    )
    _ = logs.write_text("probe\tauthority\tworkflow-result=auth-blocked\n", encoding="utf-8")

    # When
    result = run_project_script(
        "wait_workflow.py",
        "--workflow",
        "wif-probe.yml",
        "--expected-head-sha",
        EXPECTED_SHA,
        "--require-success-or-auth-blocked",
        "--runs-file",
        str(runs),
        "--logs-file",
        str(logs),
        "--timeout-seconds",
        "0",
    )

    # Then
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "auth-blocked"


def test_rejects_stale_workflow_head(tmp_path: Path) -> None:
    # Given
    runs = tmp_path / "stale-runs.json"
    _ = runs.write_text(
        f"""[
  {{"databaseId":21,"headSha":"{STALE_SHA}","status":"completed","conclusion":"success","createdAt":"2026-08-27T00:00:00Z","url":"https://example.invalid/21"}}
]\n""",
        encoding="utf-8",
    )

    # When
    result = run_project_script(
        "wait_workflow.py",
        "--workflow",
        "wif-probe.yml",
        "--expected-head-sha",
        EXPECTED_SHA,
        "--require-success-or-auth-blocked",
        "--runs-file",
        str(runs),
        "--timeout-seconds",
        "0",
    )

    # Then
    assert result.returncode == 3
    assert "stale-workflow-head" in result.stderr


def test_times_out_hung_workflow_without_sleeping(tmp_path: Path) -> None:
    # Given
    runs = tmp_path / "hung-runs.json"
    _ = runs.write_text(
        f"""[
  {{"databaseId":31,"headSha":"{EXPECTED_SHA}","status":"in_progress","conclusion":null,"createdAt":"2026-08-27T00:00:00Z","url":"https://example.invalid/31"}}
]\n""",
        encoding="utf-8",
    )

    # When
    result = run_project_script(
        "wait_workflow.py",
        "--workflow",
        "wif-probe.yml",
        "--expected-head-sha",
        EXPECTED_SHA,
        "--require-success-or-auth-blocked",
        "--runs-file",
        str(runs),
        "--timeout-seconds",
        "0",
    )

    # Then
    assert result.returncode == 3
    assert "workflow-timeout" in result.stderr


def test_rejects_malformed_run_json(tmp_path: Path) -> None:
    # Given
    runs = tmp_path / "malformed-runs.json"
    _ = runs.write_text('[{"headSha":42}]\n', encoding="utf-8")

    # When
    result = run_project_script(
        "wait_workflow.py",
        "--workflow",
        "wif-probe.yml",
        "--expected-head-sha",
        EXPECTED_SHA,
        "--require-success-or-auth-blocked",
        "--runs-file",
        str(runs),
        "--timeout-seconds",
        "0",
    )

    # Then
    assert result.returncode == 3
    assert "invalid-workflow-json" in result.stderr
