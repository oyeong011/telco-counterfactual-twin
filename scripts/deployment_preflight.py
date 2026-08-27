#!/usr/bin/env -S uv run --project backend python
"""Create or validate a secret-free deployment-authority report."""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Final

import typer
from pydantic import ValidationError
from telco_twin.bootstrap.preflight_contract import (
    Outcome,
    PreflightReport,
    ProbeStatus,
    ProviderResult,
    RepositoryResult,
    contains_secret,
    receipt_for,
)
from telco_twin.bootstrap.provider_probes import probe_all

SENSITIVE_MARKERS: Final = ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "PRIVATE_KEY")
DEFAULT_OUT: Final = Path("artifacts/deployment/preflight.json")
DEFAULT_REPO_ROOT: Final = Path(".")


def _sensitive_values() -> tuple[str, ...]:
    return tuple(
        value
        for name, value in os.environ.items()
        if value and any(marker in name.upper() for marker in SENSITIVE_MARKERS)
    )


def _clean_worktree(repo_root: Path) -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and not result.stdout.strip()


def _repository_result(
    providers: tuple[ProviderResult, ...],
    bootstrap_sha: str,
    offline: bool,
) -> RepositoryResult:
    github = providers[0]
    github_ready = github.status is ProbeStatus.READY
    return RepositoryResult(
        repository="oyeong011/telco-counterfactual-twin",
        local_worktree_clean=True,
        remote_main_matches_bootstrap=github_ready and not offline,
        public_nonfork_main_mit=github_ready and not offline,
        workflow_active=github_ready and not offline,
        evidence=receipt_for("repository", bootstrap_sha, github.status),
    )


def _report(repo_root: Path, bootstrap_sha: str, offline: bool) -> PreflightReport:
    if not _clean_worktree(repo_root):
        typer.echo("dirty-worktree", err=True)
        raise typer.Exit(code=3)
    providers = probe_all(repo_root, bootstrap_sha, offline)
    repository = _repository_result(providers, bootstrap_sha, offline)
    all_ready = all(provider.status is ProbeStatus.READY for provider in providers)
    repo_ready = (
        repository.remote_main_matches_bootstrap
        and repository.public_nonfork_main_mit
        and repository.workflow_active
    )
    outcome: Outcome = (
        "deployment-ready" if all_ready and repo_ready else "deployment-blocked"
    )
    generated_at = (
        datetime.now(tz=UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    return PreflightReport(
        schema_version="1.0",
        generated_at=generated_at,
        bootstrap_sha=bootstrap_sha,
        outcome=outcome,
        cost_control="preflight-only",
        repository=repository,
        providers=providers,
        temporary_resources=(),
        report_evidence=receipt_for("preflight", bootstrap_sha, outcome),
    )


def _read_redacted(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        typer.echo("unreadable-preflight-input", err=True)
        raise typer.Exit(code=3) from None
    if contains_secret(text, _sensitive_values()):
        typer.echo("secret-like-value", err=True)
        raise typer.Exit(code=3)
    return text


def _validation_error_code(error: ValidationError, provider: bool) -> str:
    rendered = str(error)
    if provider and "provider-status-inconsistent" in rendered:
        return "provider-status-inconsistent"
    if "report-outcome-inconsistent" in rendered:
        return "report-outcome-inconsistent"
    return "invalid-provider-report" if provider else "invalid-preflight-report"


def main(
    bootstrap_sha: Annotated[str | None, typer.Option("--bootstrap-sha")] = None,
    report: Annotated[bool, typer.Option("--report")] = False,
    out: Annotated[Path, typer.Option("--out")] = DEFAULT_OUT,
    validate: Annotated[Path | None, typer.Option("--validate")] = None,
    validate_provider: Annotated[
        Path | None, typer.Option("--validate-provider")
    ] = None,
    offline: Annotated[bool, typer.Option("--offline")] = False,
    repo_root: Annotated[
        Path, typer.Option("--repo-root", exists=True, file_okay=False)
    ] = DEFAULT_REPO_ROOT,
) -> None:
    """Run exactly one report or validation action."""
    action_count = (
        int(report) + int(validate is not None) + int(validate_provider is not None)
    )
    if action_count != 1:
        typer.echo("exactly-one-action-required", err=True)
        raise typer.Exit(code=3)
    if validate is not None:
        text = _read_redacted(validate)
        try:
            _ = PreflightReport.model_validate_json(text)
        except ValidationError as error:
            typer.echo(_validation_error_code(error, provider=False), err=True)
            raise typer.Exit(code=3) from None
        typer.echo("preflight-report-valid")
        return
    if validate_provider is not None:
        text = _read_redacted(validate_provider)
        try:
            _ = ProviderResult.model_validate_json(text)
        except ValidationError as error:
            typer.echo(_validation_error_code(error, provider=True), err=True)
            raise typer.Exit(code=3) from None
        typer.echo("provider-report-valid")
        return
    if bootstrap_sha is None:
        typer.echo("bootstrap-sha-required", err=True)
        raise typer.Exit(code=3)
    try:
        result = _report(repo_root.resolve(), bootstrap_sha, offline)
    except ValidationError:
        typer.echo("invalid-preflight-report", err=True)
        raise typer.Exit(code=3) from None
    text = result.model_dump_json(indent=2) + "\n"
    if contains_secret(text, _sensitive_values()):
        typer.echo("secret-like-value", err=True)
        raise typer.Exit(code=3)
    out.parent.mkdir(parents=True, exist_ok=True)
    _ = out.write_text(text, encoding="utf-8")
    typer.echo(result.outcome)


if __name__ == "__main__":
    typer.run(main)
