from __future__ import annotations

import json
import subprocess

import pytest

from telco_twin.bootstrap import gcp_commands
from telco_twin.bootstrap.gcp_commands import GcpContext, ProvisioningError
from telco_twin.bootstrap.gcp_reconciliation import ReconciliationPolicy
from telco_twin.bootstrap.gcp_resource_contract import (
    BudgetCleanupTarget,
    BudgetRollbackIntent,
    parse_budget,
)
from telco_twin.bootstrap.gcp_temporary_mutations import cleanup_budget

from .gcp_eventual_fakes import FakeClock

CONTEXT = GcpContext(
    project_id="example-project",
    project_number="987654321",
    billing_account_id="ABC",
    owner_id="12345678",
)


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

    def run(
        arguments: tuple[str, ...],
        *,
        timeout_seconds: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        _ = timeout_seconds
        rendered = " ".join(arguments)
        commands.append(rendered)
        snapshot = budget_snapshot(
            "twin-preflight-test",
            "projects/example-project/topics/twin-preflight-test",
            ("projects/987654321",),
            name=budget_name,
        )
        stdout = f"[{snapshot}]" if "billing budgets list" in rendered else ""
        return subprocess.CompletedProcess(arguments, 0, stdout, "")

    monkeypatch.setattr(gcp_commands, "run_gcloud", run)
    clock = FakeClock()
    policy = ReconciliationPolicy(monotonic=clock.monotonic, sleeper=clock.sleep)
    intent = BudgetRollbackIntent(CONTEXT, "twin-preflight-test", policy)

    # When
    cleaned = cleanup_budget(intent)

    # Then
    assert cleaned is False
    assert all("billing budgets delete" not in command for command in commands)


def budget_snapshot(
    display_name: str,
    pubsub_topic: str,
    projects: tuple[str, ...],
    *,
    name: str = "billingAccounts/ABC/budgets/123",
) -> str:
    """Render one typed Budget API snapshot fixture."""
    return json.dumps(
        {
            "name": name,
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


@pytest.mark.parametrize("match_count", [0, 2])
def test_budget_cleanup_fails_closed_without_one_exact_match(
    match_count: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    commands: list[str] = []
    snapshots = ",".join(
        budget_snapshot(
            "twin-preflight-test",
            "projects/example-project/topics/twin-preflight-test",
            ("projects/987654321",),
            name=f"billingAccounts/ABC/budgets/{index}",
        )
        for index in range(match_count)
    )

    def run(
        arguments: tuple[str, ...],
        *,
        timeout_seconds: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        _ = timeout_seconds
        commands.append(" ".join(arguments))
        return subprocess.CompletedProcess(arguments, 0, f"[{snapshots}]", "")

    monkeypatch.setattr(gcp_commands, "run_gcloud", run)
    clock = FakeClock()
    policy = ReconciliationPolicy(monotonic=clock.monotonic, sleeper=clock.sleep)
    intent = BudgetRollbackIntent(CONTEXT, "twin-preflight-test", policy)

    # When
    cleaned = cleanup_budget(intent)

    # Then
    assert cleaned is False
    assert all("billing budgets delete" not in command for command in commands)
