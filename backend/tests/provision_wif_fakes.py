"""Reusable fake CLI boundaries for provision-WIF integration tests."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

FAKE_HEAD_SHA = "c" * 40


def write_deny_workflow_tools(tool_dir: Path) -> None:
    """Create fake git/gh commands for an expected deny-exchange result."""
    git = tool_dir / "git"
    gh = tool_dir / "gh"
    _ = git.write_text(
        f"#!/bin/sh\nprintf '%s\\n' '{FAKE_HEAD_SHA}'\n",
        encoding="utf-8",
    )
    _ = gh.write_text(
        f"""#!/bin/sh
case "$*" in
  "api users/oyeong011"*) printf '%s\\n' '12345678' ;;
  "run list"*) printf '%s\\n' '[]' ;;
  "workflow run"*) printf '%s\\n' 'https://example.invalid/actions/runs/123' ;;
  "run watch"*) if test "${{FAKE_DENY_ACCEPTED:-0}}" = 1; then exit 1; fi ;;
  *"--json headSha,status,conclusion,url"*)
    if test "${{FAKE_DENY_ACCEPTED:-0}}" = 1; then
      conclusion=failure
    else
      conclusion=success
    fi
    metadata='{{"headSha":"{FAKE_HEAD_SHA}","status":"completed","conclusion":"%s","url":"x"}}'
    printf "$metadata\\n" "$conclusion"
    ;;
  *"--json headSha,conclusion,url"*)
    if test "${{FAKE_DENY_ACCEPTED:-0}}" = 1; then
      conclusion=failure
    else
      conclusion=success
    fi
    printf '{{"headSha":"{FAKE_HEAD_SHA}","conclusion":"%s","url":"x"}}\\n' "$conclusion"
    ;;
  *"--log"*)
    printf 'job\\tassert\\t2026-08-27T00:00:00Z workflow-result=deny-control-succeeded\\n'
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


def write_first_run_tools(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create fake gh/gcloud binaries whose service account begins absent."""
    tool_dir = tmp_path / "first-run-bin"
    tool_dir.mkdir()
    command_log = tmp_path / "first-run-gcloud.log"
    service_account_state = tmp_path / "service-account-created"
    gcloud = tool_dir / "gcloud"
    _ = gcloud.write_text(
        """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_GCLOUD_LOG"
budget_state="$FAKE_GCLOUD_LOG-budget"
case "$*" in
  *"auth list"*) printf '%s\\n' 'test-account@example.invalid' ;;
  *"projects describe"*) printf '%s\\n' '987654321' ;;
  *"service-accounts describe"*) test -f "$FAKE_SA_STATE"; exit $? ;;
  *"service-accounts get-iam-policy"*)
    if test -f "$FAKE_SA_STATE"; then printf '%s\\n' '{"bindings":[]}'; else exit 1; fi
    ;;
  *"service-accounts create"*) : > "$FAKE_SA_STATE" ;;
  *"providers describe"*)
    printf '%s\\n' '{"oidc":{"issuerUri":"x"},"attributeMapping":{},"attributeCondition":"false"}'
    ;;
  *"billing budgets create"*)
    if test "${FAKE_FAIL_BUDGET:-0}" = 1; then exit 1; fi
    for arg in "$@"; do
      case "$arg" in
        --display-name=*) printf '%s' "$arg" | cut -d= -f2- > "$budget_state" ;;
      esac
    done
    printf '%s\\n' 'billingAccounts/ABC/budgets/123'
    ;;
  *"billing budgets describe"*)
    if test "${FAKE_WRONG_SCHEMA:-0}" = 1; then
      schema=2.0
    else
      schema=1.0
    fi
    display="$(cat "$budget_state")"
    prefix='{"name":"billingAccounts/ABC/budgets/123","displayName":"'
    middle='","budgetFilter":{"projects":["projects/987654321"]},"notificationsRule":{"schemaVersion":"'
    suffix='","pubsubTopic":"projects/example-project/topics/'
    printf '%s%s%s%s%s%s%s\\n' "$prefix" "$display" "$middle" "$schema" \
      "$suffix" "$display" '"}}'
    ;;
  *"pubsub topics get-iam-policy"*)
    if test "${FAKE_WRONG_PUBLISHER:-0}" = 1; then
      member=wrong@example.invalid
    else
      member=billing-budget-alert@system.gserviceaccount.com
    fi
    prefix='{"bindings":[{"role":"roles/pubsub.publisher","members":["serviceAccount:'
    printf '%s%s%s\\n' "$prefix" "$member" '"]}]}'
    ;;
esac
exit 0
""",
        encoding="utf-8",
    )
    gcloud.chmod(0o755)
    write_deny_workflow_tools(tool_dir)
    return tool_dir, command_log, service_account_state


def first_run_environment(tool_dir: Path, command_log: Path, state: Path) -> dict[str, str]:
    """Build the isolated environment for a first-run WIF probe."""
    return {
        "PATH": f"{tool_dir}:{os.environ['PATH']}",
        "FAKE_GCLOUD_LOG": str(command_log),
        "FAKE_SA_STATE": str(state),
        "GCP_PROJECT_ID": "example-project",
        "GCP_REGION": "asia-northeast3",
        "GCP_BILLING_ACCOUNT_ID": "ABC",
    }
