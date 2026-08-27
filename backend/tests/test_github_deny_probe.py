from __future__ import annotations

import os
from pathlib import Path

import pytest

from telco_twin.bootstrap.github_deny_probe import assert_deny_exchange
from telco_twin.bootstrap.probe_errors import ProviderProbeError

WORKFLOW_PATH = Path(__file__).resolve().parents[2] / ".github/workflows/wif-probe.yml"
HEAD_SHA = "a" * 40
PROVIDER_RESOURCE = (
    "projects/987654321/locations/global/workloadIdentityPools/"
    "github-actions/providers/github-oidc-deny-test"
)
SERVICE_ACCOUNT = "skt-portfolio-deployer@example-project.iam.gserviceaccount.com"


def install_fake_git_and_gh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    deny_accepted: bool,
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
    if test "${{FAKE_DISPATCH_FAILS:-0}}" = 1; then exit 1; fi
    if test "[object Object]" = 1; then
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
    if test "${{FAKE_DENY_ACCEPTED:-0}}" = 1; then exit 1; fi
    ;;
  *"--json headSha,conclusion,url"*)
    if test "${{FAKE_DENY_ACCEPTED:-0}}" = 1; then
      conclusion=failure
    else
      conclusion=success
    fi
    printf '{{"headSha":"{HEAD_SHA}","conclusion":"%s","url":"x"}}\\n' "$conclusion"
    ;;
  *"--log"*)
    if test "${{FAKE_DENY_ACCEPTED:-0}}" = 1; then
      marker=deny-unexpected-success
    else
      marker=deny-rejected
    fi
    printf 'job\\tassert\\t2026-08-27T00:00:00Z workflow-result=%s\\n' "$marker"
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
    monkeypatch.setenv("FAKE_DENY_ACCEPTED", "1" if deny_accepted else "0")
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
    command_log = install_fake_git_and_gh(tmp_path, monkeypatch, deny_accepted=False)

    # When
    receipt = assert_deny_exchange(PROVIDER_RESOURCE, SERVICE_ACCOUNT, "example-project")

    # Then
    assert receipt.run_id == 123
    assert receipt.head_sha == HEAD_SHA
    commands = command_log.read_text(encoding="utf-8")
    assert "workflow run wif-probe.yml --ref main -f mode=deny-probe" in commands
    assert f"-f provider={PROVIDER_RESOURCE}" in commands
    assert f"-f service_account={SERVICE_ACCOUNT}" in commands
    assert "-f project_id=example-project" in commands


def test_deny_probe_makes_unexpected_token_exchange_success_fatal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    _ = install_fake_git_and_gh(tmp_path, monkeypatch, deny_accepted=True)

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
        deny_accepted=False,
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
        deny_accepted=False,
        dispatch_returns_url=False,
    )

    # When
    receipt = assert_deny_exchange(PROVIDER_RESOURCE, SERVICE_ACCOUNT, "example-project")

    # Then
    assert receipt.run_id == 123
    assert "run list --workflow wif-probe.yml" in command_log.read_text(encoding="utf-8")


def test_workflow_asserts_deny_exchange_failure_as_a_machine_contract() -> None:
    # Given
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    # When
    machine_tokens = (
        "deny-probe",
        "continue-on-error: true",
        "${{ steps.deny_auth.outcome }}",
        '== "success"',
        "workflow-result=deny-unexpected-success",
        "workflow-result=deny-rejected",
    )

    # Then
    assert all(token in workflow for token in machine_tokens)
