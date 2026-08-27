from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import pytest

from telco_twin.bootstrap import github_deny_probe
from telco_twin.bootstrap.github_deny_probe import assert_deny_exchange
from telco_twin.bootstrap.probe_errors import ProviderProbeError

WORKFLOW_PATH = Path(__file__).resolve().parents[2] / ".github/workflows/wif-probe.yml"
HEAD_SHA = "a" * 40
PROVIDER_RESOURCE = (
    "projects/987654321/locations/global/workloadIdentityPools/"
    "github-actions/providers/github-oidc-deny-test"
)
SERVICE_ACCOUNT = "skt-portfolio-deployer@example-project.iam.gserviceaccount.com"
MATCHING_PROVIDER_RESOURCE = (
    "projects/987654321/locations/global/workloadIdentityPools/github-actions/providers/github-oidc"
)
type DenyScenario = Literal[
    "rejected",
    "unexpected-success",
    "unrelated-failure",
    "control-failure",
    "missing-control-proof",
    "timeout",
]


def install_fake_git_and_gh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    scenario: DenyScenario = "rejected",
    dispatch_fails: bool = False,
    dispatch_returns_url: bool = True,
) -> Path:
    """Install fake Git/GitHub CLIs for the exact deny-exchange workflow path."""
    tool_dir = tmp_path / "bin"
    tool_dir.mkdir()
    command_log = tmp_path / "gh.log"
    git = tool_dir / "git"
    gh = tool_dir / "gh"
    _ = git.write_text(
        f"#!/bin/sh\nprintf '%s\\n' '{HEAD_SHA}'\n",
        encoding="utf-8",
    )
    _ = gh.write_text(
        f"""#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_GH_LOG"
case "$*" in
  "workflow run"*)
    if test "$FAKE_DISPATCH_FAILS" = 1; then exit 1; fi
    if test "$FAKE_DISPATCH_RETURNS_URL" = 1; then
      printf '%s\\n' 'https://example.invalid/actions/runs/123'
    else
      : > "$FAKE_DISPATCH_MARKER"
    fi
    ;;
  "run list"*)
    if test -f "$FAKE_DISPATCH_MARKER"; then
      printf '%s\\n' '[{{"databaseId":123,"headSha":"{HEAD_SHA}","createdAt":"2026-08-27T00:00:00Z","url":"https://example.invalid/actions/runs/123"}}]'
    else
      printf '%s\\n' '[]'
    fi
    ;;
  "run watch"*)
    if test "$FAKE_DENY_SCENARIO" != rejected; then exit 124; fi
    ;;
  *"--json headSha,status,conclusion,url"*)
    if test "$FAKE_DENY_SCENARIO" = timeout; then
      printf '{{"headSha":"{HEAD_SHA}","status":"in_progress","conclusion":"","url":"x"}}\\n'
    elif test "$FAKE_DENY_SCENARIO" = rejected ||
      test "$FAKE_DENY_SCENARIO" = missing-control-proof; then
      printf '{{"headSha":"{HEAD_SHA}","status":"completed","conclusion":"success","url":"x"}}\\n'
    else
      printf '{{"headSha":"{HEAD_SHA}","status":"completed","conclusion":"failure","url":"x"}}\\n'
    fi
    ;;
  *"--json headSha,conclusion,url"*)
    if test "$FAKE_DENY_SCENARIO" = rejected ||
      test "$FAKE_DENY_SCENARIO" = missing-control-proof; then
      conclusion=success
    else
      conclusion=failure
    fi
    printf '{{"headSha":"{HEAD_SHA}","conclusion":"%s","url":"x"}}\\n' "$conclusion"
    ;;
  *"--log"*)
    case "$FAKE_DENY_SCENARIO" in
      rejected)
        printf 'job\\tassert\\t2026-08-27T00:00:00Z workflow-result=deny-control-succeeded\\n'
        printf 'job\\tassert\\t2026-08-27T00:00:01Z workflow-result=deny-rejected\\n'
        ;;
      unexpected-success)
        printf 'job\\tassert\\t2026-08-27T00:00:00Z workflow-result=deny-control-succeeded\\n'
        printf 'job\\tassert\\t2026-08-27T00:00:01Z workflow-result=deny-unexpected-success\\n'
        ;;
      control-failure)
        printf 'job\\tassert\\t2026-08-27T00:00:00Z workflow-result=deny-control-failed\\n'
        ;;
      unrelated-failure)
        printf 'job\\tassert\\t2026-08-27T00:00:00Z workflow-result=deny-auth-unrelated-failure\\n'
        ;;
      missing-control-proof)
        printf 'job\\tassert\\t2026-08-27T00:00:00Z workflow-result=deny-rejected\\n'
        ;;
    esac
    ;;
esac
exit 0
""",
        encoding="utf-8",
    )
    git.chmod(0o755)
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tool_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_GH_LOG", str(command_log))
    monkeypatch.setenv("FAKE_DISPATCH_MARKER", str(tmp_path / "dispatched"))
    monkeypatch.setenv("FAKE_DENY_SCENARIO", scenario)
    monkeypatch.setenv("FAKE_DISPATCH_FAILS", "1" if dispatch_fails else "0")
    monkeypatch.setenv(
        "FAKE_DISPATCH_RETURNS_URL",
        "1" if dispatch_returns_url else "0",
    )
    return command_log


def test_deny_probe_dispatches_exact_provider_and_requires_rejection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    command_log = install_fake_git_and_gh(tmp_path, monkeypatch)

    # When
    receipt = assert_deny_exchange(PROVIDER_RESOURCE, SERVICE_ACCOUNT, "example-project")

    # Then
    assert receipt.run_id == 123
    assert receipt.head_sha == HEAD_SHA
    commands = command_log.read_text(encoding="utf-8")
    assert "workflow run wif-probe.yml --ref main -f mode=deny-probe" in commands
    assert f"-f provider={PROVIDER_RESOURCE}" in commands
    assert f"-f matching_provider={MATCHING_PROVIDER_RESOURCE}" in commands
    assert f"-f service_account={SERVICE_ACCOUNT}" in commands
    assert "-f project_id=example-project" in commands


def test_deny_probe_makes_unexpected_token_exchange_success_fatal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    _ = install_fake_git_and_gh(
        tmp_path,
        monkeypatch,
        scenario="unexpected-success",
    )

    # When / Then
    with pytest.raises(ProviderProbeError, match="deny-exchange-unexpected-success"):
        _ = assert_deny_exchange(PROVIDER_RESOURCE, SERVICE_ACCOUNT, "example-project")


def test_deny_probe_rejects_workflow_dispatch_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    _ = install_fake_git_and_gh(
        tmp_path,
        monkeypatch,
        dispatch_fails=True,
    )

    # When / Then
    with pytest.raises(ProviderProbeError, match="deny-workflow-dispatch-failed"):
        _ = assert_deny_exchange(PROVIDER_RESOURCE, SERVICE_ACCOUNT, "example-project")


def test_deny_probe_resolves_run_when_dispatch_stdout_is_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    command_log = install_fake_git_and_gh(
        tmp_path,
        monkeypatch,
        dispatch_returns_url=False,
    )

    # When
    receipt = assert_deny_exchange(PROVIDER_RESOURCE, SERVICE_ACCOUNT, "example-project")

    # Then
    assert receipt.run_id == 123
    assert "run list --workflow wif-probe.yml" in command_log.read_text(encoding="utf-8")


def test_deny_probe_rejects_missing_positive_control_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    _ = install_fake_git_and_gh(
        tmp_path,
        monkeypatch,
        scenario="missing-control-proof",
    )

    # When / Then
    with pytest.raises(ProviderProbeError, match="deny-exchange-rejection-unproven"):
        _ = assert_deny_exchange(PROVIDER_RESOURCE, SERVICE_ACCOUNT, "example-project")


def test_deny_probe_rejects_unrelated_auth_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    _ = install_fake_git_and_gh(
        tmp_path,
        monkeypatch,
        scenario="unrelated-failure",
    )

    # When / Then
    with pytest.raises(ProviderProbeError, match="deny-exchange-rejection-unproven"):
        _ = assert_deny_exchange(PROVIDER_RESOURCE, SERVICE_ACCOUNT, "example-project")


def test_deny_probe_makes_matching_control_failure_fatal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    _ = install_fake_git_and_gh(
        tmp_path,
        monkeypatch,
        scenario="control-failure",
    )

    # When / Then
    with pytest.raises(ProviderProbeError, match="deny-exchange-control-failed"):
        _ = assert_deny_exchange(PROVIDER_RESOURCE, SERVICE_ACCOUNT, "example-project")


def test_deny_probe_times_out_without_unbounded_run_watch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    _ = install_fake_git_and_gh(tmp_path, monkeypatch, scenario="timeout")
    monotonic_values = iter((0.0, 1.0))
    monkeypatch.setattr(
        github_deny_probe,
        "RUN_COMPLETION_TIMEOUT_SECONDS",
        0.5,
        raising=False,
    )
    monkeypatch.setattr(
        "telco_twin.bootstrap.github_deny_probe.time.monotonic",
        monotonic_values.__next__,
    )

    # When / Then
    with pytest.raises(ProviderProbeError, match="deny-workflow-timeout"):
        _ = assert_deny_exchange(PROVIDER_RESOURCE, SERVICE_ACCOUNT, "example-project")


def test_workflow_asserts_deny_exchange_failure_as_a_machine_contract() -> None:
    # Given
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    # When
    machine_tokens = (
        "deny-probe",
        "matching_provider",
        "id: control_auth",
        "${{ steps.control_auth.outcome }}",
        "continue-on-error: true",
        "timeout 15s gcloud iam workload-identity-pools providers describe",
        "timeout 180s uv run --project backend python scripts/deny_exchange_probe.py",
        "id: deny_classify",
        "${{ steps.deny_classify.outputs.status }}",
        "workflow-result=deny-control-failed",
        "workflow-result=deny-control-succeeded",
        "workflow-result=deny-exchange-rejection-unproven",
        "workflow-result=deny-unexpected-success",
        "workflow-result=deny-rejected",
    )

    # Then
    assert all(token in workflow for token in machine_tokens)
    assert "id: deny_auth" not in workflow
