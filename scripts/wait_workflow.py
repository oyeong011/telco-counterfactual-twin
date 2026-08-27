#!/usr/bin/env -S uv run --project backend python
"""Wait for a GitHub workflow run bound to an exact commit head."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Annotated, ClassVar, Final, Literal

import typer
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from telco_twin.bootstrap.gcp_commands import run_command

type RunStatus = Literal[
    "queued", "in_progress", "completed", "requested", "waiting", "pending"
]
type Conclusion = Literal[
    "success",
    "failure",
    "cancelled",
    "skipped",
    "timed_out",
    "action_required",
    "neutral",
    "startup_failure",
    "stale",
]
type RawConclusion = Conclusion | Literal[""] | None

AUTH_BLOCKED_MARKER: Final = "workflow-result=auth-blocked"
READY_MARKER: Final = "workflow-result=success"
AUTH_BLOCKED_LOG_LINE: Final = re.compile(
    rf"^\d{{4}}-\d{{2}}-\d{{2}}T\d{{2}}:\d{{2}}:\d{{2}}(?:\.\d+)?Z {AUTH_BLOCKED_MARKER}$"
)
READY_LOG_LINE: Final = re.compile(
    rf"^\d{{4}}-\d{{2}}-\d{{2}}T\d{{2}}:\d{{2}}:\d{{2}}(?:\.\d+)?Z {READY_MARKER}$"
)


class WorkflowRun(BaseModel):
    """GitHub CLI workflow-run projection."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    database_id: int = Field(alias="databaseId")
    head_sha: str = Field(alias="headSha", pattern=r"^[0-9a-f]{40}$")
    status: RunStatus
    conclusion: RawConclusion
    created_at: str = Field(alias="createdAt", min_length=1)
    url: str = Field(min_length=1)


RUNS_ADAPTER: Final = TypeAdapter(tuple[WorkflowRun, ...])


def _load_runs(
    workflow: str,
    runs_file: Path | None,
    command_timeout_seconds: float,
) -> tuple[WorkflowRun, ...]:
    if runs_file is not None:
        raw = runs_file.read_text(encoding="utf-8")
    else:
        result = run_command(
            (
                "gh",
                "run",
                "list",
                "--workflow",
                workflow,
                "--event",
                "workflow_dispatch",
                "--limit",
                "20",
                "--json",
                "databaseId,headSha,status,conclusion,createdAt,url",
            ),
            timeout_seconds=command_timeout_seconds,
        )
        if result.returncode != 0:
            typer.echo("workflow-query-failed", err=True)
            raise typer.Exit(code=3)
        raw = result.stdout
    try:
        return RUNS_ADAPTER.validate_json(raw)
    except ValidationError:
        typer.echo("invalid-workflow-json", err=True)
        raise typer.Exit(code=3) from None


def _load_logs(
    run_id: int,
    logs_file: Path | None,
    command_timeout_seconds: float,
) -> str:
    if logs_file is not None:
        return logs_file.read_text(encoding="utf-8")
    result = run_command(
        ("gh", "run", "view", str(run_id), "--log"),
        timeout_seconds=command_timeout_seconds,
    )
    if result.returncode != 0:
        typer.echo("workflow-log-query-failed", err=True)
        raise typer.Exit(code=3)
    return result.stdout


def _has_marker(logs: str, marker: re.Pattern[str]) -> bool:
    return any(
        marker.fullmatch(line.rsplit("\t", 1)[-1].strip()) is not None
        for line in logs.splitlines()
    )


def main(
    workflow: Annotated[str, typer.Option("--workflow")],
    expected_head_sha: Annotated[str, typer.Option("--expected-head-sha")],
    require_success_or_auth_blocked: Annotated[
        bool,
        typer.Option("--require-success-or-auth-blocked"),
    ] = False,
    runs_file: Annotated[Path | None, typer.Option("--runs-file")] = None,
    logs_file: Annotated[Path | None, typer.Option("--logs-file")] = None,
    timeout_seconds: Annotated[float, typer.Option("--timeout-seconds", min=0)] = 300,
    poll_interval: Annotated[float, typer.Option("--poll-interval", min=0.1)] = 2,
    command_timeout_seconds: Annotated[
        float,
        typer.Option("--command-timeout-seconds", min=0.01),
    ] = 15,
) -> None:
    """Wait until the exact-head run completes, rejecting stale or hung runs."""
    deadline = time.monotonic() + timeout_seconds
    observed_stale = False
    while True:
        runs = _load_runs(workflow, runs_file, command_timeout_seconds)
        matching = tuple(run for run in runs if run.head_sha == expected_head_sha)
        observed_stale = observed_stale or bool(runs and not matching)
        if matching:
            run = max(matching, key=lambda item: item.created_at)
            if run.status == "completed":
                if run.conclusion != "success":
                    typer.echo("workflow-failed", err=True)
                    raise typer.Exit(code=3)
                logs = _load_logs(
                    run.database_id,
                    logs_file,
                    command_timeout_seconds,
                )
                if _has_marker(logs, AUTH_BLOCKED_LOG_LINE):
                    if not require_success_or_auth_blocked:
                        typer.echo("auth-blocked-not-allowed", err=True)
                        raise typer.Exit(code=3)
                    typer.echo("auth-blocked")
                    return
                if _has_marker(logs, READY_LOG_LINE):
                    typer.echo("success")
                    return
                typer.echo("workflow-result-unproven", err=True)
                raise typer.Exit(code=3)
        if time.monotonic() >= deadline:
            code = (
                "stale-workflow-head"
                if observed_stale and not matching
                else "workflow-timeout"
            )
            typer.echo(code, err=True)
            raise typer.Exit(code=3)
        time.sleep(poll_interval)


if __name__ == "__main__":
    typer.run(main)
