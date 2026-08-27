from __future__ import annotations

import json

import pytest

from telco_twin.bootstrap import gcp_resource_cleanup
from telco_twin.bootstrap.gcp_commands import GcpContext, ProvisioningError
from telco_twin.bootstrap.gcp_resource_cleanup import (
    TemporaryCleanupPlan,
    cleanup_temporary,
)
from telco_twin.bootstrap.gcp_resource_contract import BudgetCleanupTarget, parse_budget

CONTEXT = GcpContext(
    project_id="example-project",
    project_number="987654321",
    billing_account_id="ABC",
    owner_id="12345678",
)
SERVICE_ACCOUNT = "skt-portfolio-deployer@example-project.iam.gserviceaccount.com"


@pytest.mark.parametrize(
    "budget_name",
    [
        "billingAccounts/OTHER/budgets/existing",
        "billingAccounts/ABCD/budgets/confused",
        "billingAccounts/ABC/budgets/one/extra",
        "billingAccounts/ABC/not-budgets/value",
    ],
)
def test_cleanup_rejects_unowned_budget_and_continues(
    budget_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    commands: list[str] = []

    def attempt(arguments: tuple[str, ...]) -> bool:
        commands.append(" ".join(arguments))
        return True

    monkeypatch.setattr(gcp_resource_cleanup, "attempt_gcloud", attempt)
    budget = BudgetCleanupTarget(
        resource_name=budget_name,
        billing_account_id="ABC",
        display_name="twin-preflight-test",
        topic_resource="projects/example-project/topics/twin-preflight-test",
        project_resource="projects/987654321",
    )
    plan = TemporaryCleanupPlan(
        context=CONTEXT,
        service_account=SERVICE_ACCOUNT,
        budget=budget,
        binding_created=True,
        deny_member="principalSet://example.invalid/member",
        provider_created=True,
        deny_provider="github-oidc-deny-test",
        topic_created=True,
        topic="twin-preflight-test",
    )

    # When
    failures = cleanup_temporary(plan)

    # Then
    assert failures == ("budget-ownership",)
    assert all("billing budgets delete" not in command for command in commands)
    assert any("remove-iam-policy-binding" in command for command in commands)
    assert any("providers delete" in command for command in commands)
    assert any("pubsub topics delete" in command for command in commands)


def budget_snapshot(
    display_name: str,
    pubsub_topic: str,
    projects: tuple[str, ...],
) -> str:
    """Render one typed Budget API snapshot fixture."""
    return json.dumps(
        {
            "name": "billingAccounts/ABC/budgets/123",
            "displayName": display_name,
            "budgetFilter": {"projects": projects},
            "notificationsRule": {
                "schemaVersion": "1.0",
                "pubsubTopic": pubsub_topic,
            },
        }
    )


@pytest.mark.parametrize(
    ("display_name", "pubsub_topic", "projects"),
    [
        (
            "another-budget",
            "projects/example-project/topics/twin-preflight-test",
            ("projects/987654321",),
        ),
        (
            "twin-preflight-test",
            "projects/example-project/topics/another-topic",
            ("projects/987654321",),
        ),
        (
            "twin-preflight-test",
            "projects/example-project/topics/twin-preflight-test",
            ("projects/111111111",),
        ),
    ],
)
def test_budget_snapshot_rejects_probe_identity_mismatch(
    display_name: str,
    pubsub_topic: str,
    projects: tuple[str, ...],
) -> None:
    # Given
    snapshot = budget_snapshot(display_name, pubsub_topic, projects)

    # When / Then
    target = BudgetCleanupTarget(
        resource_name="billingAccounts/ABC/budgets/123",
        billing_account_id="ABC",
        display_name="twin-preflight-test",
        topic_resource="projects/example-project/topics/twin-preflight-test",
        project_resource="projects/987654321",
    )
    with pytest.raises(ProvisioningError):
        _ = parse_budget(snapshot, target)
