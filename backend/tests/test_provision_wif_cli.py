from __future__ import annotations

import os
from typing import TYPE_CHECKING

from .conftest import run_project_script

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
    printf '%s\\n' 'billingAccounts/ABC/budgets/123'
    ;;
  *"billing budgets describe"*)
    if test "${FAKE_WRONG_SCHEMA:-0}" = 1; then
      schema=2.0
    else
      schema=1.0
    fi
    prefix='{"name":"billingAccounts/ABC/budgets/123","notificationsRule":{"schemaVersion":"'
    printf '%s%s%s\\n' "$prefix" "$schema" '"}}'
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


def test_plan_binds_exact_repositories_and_immutable_owner_id() -> None:
    # Given
    owner_id = "12345678"

    # When
    result = run_project_script(
        "provision_wif.py",
        "--plan",
        "--project-id",
        "example-project",
        "--project-number",
        "987654321",
        "--owner-id",
        owner_id,
    )

    # Then
    assert result.returncode == 0, result.stderr
    assert '"pool_id": "github-actions"' in result.stdout
    assert '"provider_id": "github-oidc"' in result.stdout
    assert '"issuer": "https://token.actions.githubusercontent.com"' in result.stdout
    assert "attribute.repository_owner_id=assertion.repository_owner_id" in result.stdout
    assert f"assertion.repository_owner_id=='{owner_id}'" in result.stdout
    assert "oyeong011/telco-counterfactual-twin" in result.stdout
    assert "oyeong011/mcp-evidence-plane" in result.stdout


def test_apply_returns_blocked_when_gcloud_authority_is_absent(tmp_path: Path) -> None:
    # Given
    environment = {
        "PATH": str(tmp_path),
        "GCP_PROJECT_ID": "",
        "GCP_REGION": "",
        "GCP_BILLING_ACCOUNT_ID": "",
    }

    # When
    result = run_project_script("provision_wif.py", "--apply", environment=environment)

    # Then
    assert result.returncode == 2
    assert '"status": "deployment-blocked"' in result.stdout
    assert "missing-command:gcloud" in result.stdout


def test_apply_updates_existing_provider_and_cleans_temporary_resources(tmp_path: Path) -> None:
    # Given
    tool_dir = tmp_path / "bin"
    tool_dir.mkdir()
    command_log = tmp_path / "gcloud.log"
    gcloud = tool_dir / "gcloud"
    _ = gcloud.write_text(
        """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_GCLOUD_LOG"
case "$*" in
  *"auth list"*) printf '%s\\n' 'test-account@example.invalid' ;;
  *"projects describe"*) printf '%s\\n' '987654321' ;;
  *"providers describe"*)
    printf '%s\\n' '{"oidc":{"issuerUri":"x"},"attributeMapping":{},"attributeCondition":"false"}'
    ;;
  *"service-accounts get-iam-policy"*) printf '%s\\n' '{"bindings":[]}' ;;
  *"billing budgets create"*) printf '%s\\n' 'billingAccounts/ABC/budgets/123' ;;
  *"billing budgets describe"*)
    prefix='{"name":"billingAccounts/ABC/budgets/123","notificationsRule":{"schemaVersion":"'
    printf '%s%s%s\\n' "$prefix" '1.0' '"}}'
    ;;
  *"pubsub topics get-iam-policy"*)
    prefix='{"bindings":[{"role":"roles/pubsub.publisher","members":["serviceAccount:'
    printf '%s%s%s\\n' "$prefix" 'billing-budget-alert@system.gserviceaccount.com' '"]}]}'
    ;;
esac
exit 0
""",
        encoding="utf-8",
    )
    gcloud.chmod(0o755)
    write_deny_workflow_tools(tool_dir)
    environment = {
        "PATH": f"{tool_dir}:{os.environ['PATH']}",
        "FAKE_GCLOUD_LOG": str(command_log),
        "GCP_PROJECT_ID": "example-project",
        "GCP_REGION": "asia-northeast3",
        "GCP_BILLING_ACCOUNT_ID": "ABC",
    }

    # When
    result = run_project_script("provision_wif.py", "--apply", environment=environment)

    # Then
    assert result.returncode == 0, result.stderr
    assert '"status": "ready"' in result.stdout
    assert '"temporary_probe": {' in result.stdout
    assert '"budget_resource": "billingAccounts/ABC/budgets/123"' in result.stdout
    assert '"budget_schema_version": "1.0"' in result.stdout
    assert '"publisher_policy_evidence": "sha256:' in result.stdout
    commands = command_log.read_text(encoding="utf-8")
    assert "providers update-oidc github-oidc" in commands
    assert "--issuer-uri=https://token.actions.githubusercontent.com" in commands
    assert "attribute.repository_owner_id=assertion.repository_owner_id" in commands
    assert "service-accounts add-iam-policy-binding" in commands
    assert "pubsub topics create twin-preflight-" in commands
    assert "billing budgets create" in commands
    assert "billing budgets describe billingAccounts/ABC/budgets/123" in commands
    assert "billing budgets delete billingAccounts/ABC/budgets/123" in commands
    assert "pubsub topics delete twin-preflight-" in commands
    assert "providers delete github-oidc-deny-" in commands


def test_first_run_creates_service_account_before_policy_snapshot(tmp_path: Path) -> None:
    # Given
    tool_dir, command_log, state = write_first_run_tools(tmp_path)

    # When
    result = run_project_script(
        "provision_wif.py",
        "--apply",
        environment=first_run_environment(tool_dir, command_log, state),
    )

    # Then
    assert result.returncode == 0, result.stderr
    commands = command_log.read_text(encoding="utf-8")
    assert "service-accounts describe" in commands
    assert "service-accounts create skt-portfolio-deployer" in commands
    assert "service-accounts get-iam-policy" not in commands


def test_first_run_rolls_back_created_service_account_after_probe_failure(tmp_path: Path) -> None:
    # Given
    tool_dir, command_log, state = write_first_run_tools(tmp_path)
    environment = first_run_environment(tool_dir, command_log, state)
    environment["FAKE_FAIL_BUDGET"] = "1"

    # When
    result = run_project_script("provision_wif.py", "--apply", environment=environment)

    # Then
    assert result.returncode == 3
    commands = command_log.read_text(encoding="utf-8")
    assert "service-accounts create skt-portfolio-deployer" in commands
    assert "service-accounts delete skt-portfolio-deployer@example-project" in commands


def test_unexpected_deny_exchange_success_is_fatal_and_cleanup_runs(tmp_path: Path) -> None:
    # Given
    tool_dir, command_log, state = write_first_run_tools(tmp_path)
    environment = first_run_environment(tool_dir, command_log, state)
    environment["FAKE_DENY_ACCEPTED"] = "1"

    # When
    result = run_project_script("provision_wif.py", "--apply", environment=environment)

    # Then
    assert result.returncode == 3
    assert "deny-exchange-unexpected-success" in result.stderr
    commands = command_log.read_text(encoding="utf-8")
    assert "remove-iam-policy-binding" in commands
    assert "providers delete github-oidc-deny-" in commands


def test_budget_probe_rejects_wrong_publisher_principal(tmp_path: Path) -> None:
    # Given
    tool_dir, command_log, state = write_first_run_tools(tmp_path)
    environment = first_run_environment(tool_dir, command_log, state)
    environment["FAKE_WRONG_PUBLISHER"] = "1"

    # When
    result = run_project_script("provision_wif.py", "--apply", environment=environment)

    # Then
    assert result.returncode == 3
    assert "billing-publisher-edge-missing" in result.stderr


def test_budget_probe_rejects_non_v1_notification_schema(tmp_path: Path) -> None:
    # Given
    tool_dir, command_log, state = write_first_run_tools(tmp_path)
    environment = first_run_environment(tool_dir, command_log, state)
    environment["FAKE_WRONG_SCHEMA"] = "1"

    # When
    result = run_project_script("provision_wif.py", "--apply", environment=environment)

    # Then
    assert result.returncode == 3
    assert "budget-schema-version-mismatch" in result.stderr
