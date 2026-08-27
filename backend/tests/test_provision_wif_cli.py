from __future__ import annotations

import os
from typing import TYPE_CHECKING

from .conftest import run_project_script
from .provision_wif_fakes import (
    first_run_environment,
    write_deny_workflow_tools,
    write_first_run_tools,
)

if TYPE_CHECKING:
    from pathlib import Path


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
budget_state="$FAKE_GCLOUD_LOG-budget"
case "$*" in
  *"auth list"*) printf '%s\\n' 'test-account@example.invalid' ;;
  *"projects describe"*) printf '%s\\n' '987654321' ;;
  *"providers describe"*)
    printf '%s\\n' '{"oidc":{"issuerUri":"x"},"attributeMapping":{},"attributeCondition":"false"}'
    ;;
  *"service-accounts get-iam-policy"*) printf '%s\\n' '{"bindings":[]}' ;;
  *"billing budgets create"*)
    for arg in "$@"; do
      case "$arg" in
        --display-name=*) printf '%s' "$arg" | cut -d= -f2- > "$budget_state" ;;
      esac
    done
    printf '%s\\n' 'billingAccounts/ABC/budgets/123'
    ;;
  *"billing budgets describe"*)
    display="$(cat "$budget_state")"
    prefix='{"name":"billingAccounts/ABC/budgets/123","displayName":"'
    middle='","budgetFilter":{"projects":["projects/987654321"]},"notificationsRule":{"schemaVersion":"'
    suffix='","pubsubTopic":"projects/example-project/topics/'
    printf '%s%s%s%s%s%s%s\\n' "$prefix" "$display" "$middle" '1.0' \
      "$suffix" "$display" '"}}'
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
