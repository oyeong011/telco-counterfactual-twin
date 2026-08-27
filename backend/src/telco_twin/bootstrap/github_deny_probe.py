"""GitHub Actions OIDC negative-exchange proof for a temporary deny provider."""

from __future__ import annotations

import re
import subprocess
import time
from typing import ClassVar, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from telco_twin.bootstrap.deny_exchange_classifier import classify_deny_exchange
from telco_twin.bootstrap.deny_exchange_contract import DenyExchangeClassification
from telco_twin.bootstrap.deny_exchange_wire import probe_deny_exchange
from telco_twin.bootstrap.gcp_commands import COMMAND_TIMEOUT_RETURN_CODE, run_command
from telco_twin.bootstrap.preflight_contract import receipt_for
from telco_twin.bootstrap.probe_errors import ProviderProbeError

__all__ = [
    "DenyExchangeClassification",
    "assert_deny_exchange",
    "classify_deny_exchange",
    "probe_deny_exchange",
]

LOG_PREFIX = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z"
DENY_REJECTED_LINE = re.compile(f"{LOG_PREFIX} workflow-result=deny-rejected$")
DENY_UNEXPECTED_LINE = re.compile(f"{LOG_PREFIX} workflow-result=deny-unexpected-success$")
DENY_CONTROL_SUCCEEDED_LINE = re.compile(f"{LOG_PREFIX} workflow-result=deny-control-succeeded$")
DENY_CONTROL_FAILED_LINE = re.compile(f"{LOG_PREFIX} workflow-result=deny-control-failed$")
RUN_DISCOVERY_TIMEOUT_SECONDS = 60.0
RUN_DISCOVERY_POLL_SECONDS = 2.0
RUN_COMPLETION_TIMEOUT_SECONDS = 180.0
GH_COMMAND_TIMEOUT_SECONDS = 15.0

type RunStatus = Literal["queued", "in_progress", "completed", "waiting", "requested", "pending"]
type RunConclusion = (
    Literal[
        "success",
        "failure",
        "cancelled",
        "skipped",
        "timed_out",
        "action_required",
        "neutral",
        "startup_failure",
        "stale",
        "",
    ]
    | None
)


class DenyRunMetadata(BaseModel):
    """GitHub run fields bound to the current source head."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    head_sha: str = Field(alias="headSha", pattern=r"^[0-9a-f]{40}$")
    status: RunStatus
    conclusion: RunConclusion
    url: str = Field(min_length=1)


class DenyRunCandidate(BaseModel):
    """Workflow-list fields used to bind a dispatch when GitHub returns no URL."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    database_id: int = Field(alias="databaseId", gt=0)
    head_sha: str = Field(alias="headSha", pattern=r"^[0-9a-f]{40}$")
    created_at: str = Field(alias="createdAt", min_length=1)
    url: str = Field(min_length=1)


RUN_LIST_ADAPTER = TypeAdapter(tuple[DenyRunCandidate, ...])


class DenyExchangeReceipt(BaseModel):
    """Non-secret receipt proving the deny provider rejected GitHub OIDC."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    run_id: int = Field(gt=0)
    head_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    run_url: str = Field(min_length=1)
    evidence: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


def _error(code: str) -> ProviderProbeError:
    return ProviderProbeError(code)


def _run_id(output: str) -> int | None:
    path_component = urlparse(output.strip()).path.rstrip("/").rsplit("/", 1)[-1]
    if not path_component.isdigit():
        return None
    return int(path_component)


def _run_gh(arguments: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    """Run one GitHub command with a per-process timeout."""
    try:
        result = run_command(arguments, timeout_seconds=GH_COMMAND_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        code = "deny-workflow-command-timeout"
        raise _error(code) from None
    if result.returncode == COMMAND_TIMEOUT_RETURN_CODE:
        code = "deny-workflow-command-timeout"
        raise _error(code)
    return result


def _list_runs() -> tuple[DenyRunCandidate, ...]:
    result = _run_gh(
        (
            "gh",
            "run",
            "list",
            "--workflow",
            "wif-probe.yml",
            "--event",
            "workflow_dispatch",
            "--limit",
            "20",
            "--json",
            "databaseId,headSha,createdAt,url",
        )
    )
    if result.returncode != 0:
        code = "deny-workflow-list-failed"
        raise _error(code)
    try:
        return RUN_LIST_ADAPTER.validate_json(result.stdout)
    except ValidationError:
        code = "deny-workflow-list-invalid"
        raise _error(code) from None


def _resolve_run_id(
    dispatch_output: str,
    known_ids: frozenset[int],
    expected_head: str,
) -> int:
    dispatched_run_id = _run_id(dispatch_output)
    if dispatched_run_id is not None:
        return dispatched_run_id
    deadline = time.monotonic() + RUN_DISCOVERY_TIMEOUT_SECONDS
    while True:
        candidates = tuple(
            run
            for run in _list_runs()
            if run.database_id not in known_ids and run.head_sha == expected_head
        )
        if candidates:
            return max(candidates, key=lambda run: run.created_at).database_id
        if time.monotonic() >= deadline:
            code = "deny-workflow-run-unresolved"
            raise _error(code)
        time.sleep(RUN_DISCOVERY_POLL_SECONDS)


def _wait_for_completion(run_id: int, expected_head: str) -> DenyRunMetadata:
    """Poll the exact run until completion or a stable bounded timeout."""
    deadline = time.monotonic() + RUN_COMPLETION_TIMEOUT_SECONDS
    while True:
        result = _run_gh(
            (
                "gh",
                "run",
                "view",
                str(run_id),
                "--json",
                "headSha,status,conclusion,url",
            )
        )
        if result.returncode != 0:
            code = "deny-workflow-evidence-read-failed"
            raise _error(code)
        try:
            metadata = DenyRunMetadata.model_validate_json(result.stdout)
        except ValidationError:
            code = "deny-workflow-metadata-invalid"
            raise _error(code) from None
        if metadata.head_sha != expected_head:
            code = "deny-workflow-head-mismatch"
            raise _error(code)
        if metadata.status == "completed":
            return metadata
        if time.monotonic() >= deadline:
            code = "deny-workflow-timeout"
            raise _error(code)
        time.sleep(RUN_DISCOVERY_POLL_SECONDS)


def _has_marker(logs: str, marker: re.Pattern[str]) -> bool:
    return any(
        marker.fullmatch(line.rsplit("\t", 1)[-1].strip()) is not None for line in logs.splitlines()
    )


def _matching_provider_resource(deny_provider_resource: str) -> str:
    prefix, separator, _provider_id = deny_provider_resource.rpartition("/providers/")
    if not separator or not prefix:
        code = "deny-provider-resource-invalid"
        raise _error(code)
    return f"{prefix}/providers/github-oidc"


def assert_deny_exchange(
    provider_resource: str,
    service_account: str,
    project_id: str,
) -> DenyExchangeReceipt:
    """Dispatch the exact deny provider and require its token exchange to fail."""
    head_result = run_command(("git", "rev-parse", "HEAD"))
    expected_head = head_result.stdout.strip()
    if head_result.returncode != 0 or re.fullmatch(r"[0-9a-f]{40}", expected_head) is None:
        code = "deny-workflow-head-unavailable"
        raise _error(code)
    known_ids = frozenset(run.database_id for run in _list_runs())
    matching_provider = _matching_provider_resource(provider_resource)
    dispatch = _run_gh(
        (
            "gh",
            "workflow",
            "run",
            "wif-probe.yml",
            "--ref",
            "main",
            "-f",
            "mode=deny-probe",
            "-f",
            f"provider={provider_resource}",
            "-f",
            f"matching_provider={matching_provider}",
            "-f",
            f"service_account={service_account}",
            "-f",
            f"project_id={project_id}",
        )
    )
    if dispatch.returncode != 0:
        code = "deny-workflow-dispatch-failed"
        raise _error(code)
    run_id = _resolve_run_id(dispatch.stdout, known_ids, expected_head)
    metadata = _wait_for_completion(run_id, expected_head)
    logs_result = _run_gh(("gh", "run", "view", str(run_id), "--log"))
    if logs_result.returncode != 0:
        code = "deny-workflow-evidence-read-failed"
        raise _error(code)
    if _has_marker(logs_result.stdout, DENY_CONTROL_FAILED_LINE):
        code = "deny-exchange-control-failed"
        raise _error(code)
    if _has_marker(logs_result.stdout, DENY_UNEXPECTED_LINE):
        code = "deny-exchange-unexpected-success"
        raise _error(code)
    if (
        metadata.conclusion != "success"
        or not _has_marker(logs_result.stdout, DENY_CONTROL_SUCCEEDED_LINE)
        or not _has_marker(logs_result.stdout, DENY_REJECTED_LINE)
    ):
        code = "deny-exchange-rejection-unproven"
        raise _error(code)
    return DenyExchangeReceipt(
        run_id=run_id,
        head_sha=metadata.head_sha,
        run_url=metadata.url,
        evidence=receipt_for(
            "deny-exchange",
            str(run_id),
            metadata.head_sha,
            provider_resource,
        ),
    )
