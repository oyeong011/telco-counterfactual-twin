from __future__ import annotations

import os
from typing import TYPE_CHECKING

from .conftest import run_project_script

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


def test_rejects_interrupted_cleanup_receipt(tmp_path: Path) -> None:
    # Given
    receipt = tmp_path / "cleanup.json"
    _ = receipt.write_text(
        """{
  "cleanup_complete": false,
  "temporary_resources": ["topic:preflight-left-behind"],
  "restored_bindings": false
}
""",
        encoding="utf-8",
    )

    # When
    result = run_project_script("provision_wif.py", "--validate-cleanup", str(receipt))

    # Then
    assert result.returncode == 3
    assert "cleanup-incomplete" in result.stderr


def test_apply_updates_existing_provider_and_cleans_temporary_resources(tmp_path: Path) -> None:
    # Given
    tool_dir = tmp_path / "bin"
    tool_dir.mkdir()
    command_log = tmp_path / "gcloud.log"
    gcloud = tool_dir / "gcloud"
    gh = tool_dir / "gh"
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
  *"pubsub topics get-iam-policy"*) printf '%s\\n' 'roles/pubsub.publisher' ;;
esac
exit 0
""",
        encoding="utf-8",
    )
    _ = gh.write_text(
        """#!/bin/sh
printf '%s\\n' '12345678'
""",
        encoding="utf-8",
    )
    gcloud.chmod(0o755)
    gh.chmod(0o755)
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
    commands = command_log.read_text(encoding="utf-8")
    assert "providers update-oidc github-oidc" in commands
    assert "--issuer-uri=https://token.actions.githubusercontent.com" in commands
    assert "attribute.repository_owner_id=assertion.repository_owner_id" in commands
    assert "service-accounts add-iam-policy-binding" in commands
    assert "pubsub topics create twin-preflight-" in commands
    assert "billing budgets create" in commands
    assert "billing budgets delete billingAccounts/ABC/budgets/123" in commands
    assert "pubsub topics delete twin-preflight-" in commands
    assert "providers delete github-oidc-deny-" in commands
