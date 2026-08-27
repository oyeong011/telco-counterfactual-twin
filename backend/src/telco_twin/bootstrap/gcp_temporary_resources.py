"""Transactional temporary Pub/Sub topic and Budget API mutations."""

from __future__ import annotations

from telco_twin.bootstrap.gcp_commands import GcpContext, ProvisioningError
from telco_twin.bootstrap.gcp_reconciliation import (
    DEFAULT_RECONCILIATION_POLICY,
    ReconciliationPolicy,
)
from telco_twin.bootstrap.gcp_resource_contract import (
    BudgetCleanupTarget,
    BudgetRollbackIntent,
    BudgetSnapshot,
    TopicRollbackIntent,
    TopicSnapshot,
    parse_budget_list,
    parse_budget_target,
    parse_topic_list,
)


def _topic_list(intent: TopicRollbackIntent) -> tuple[TopicSnapshot, ...]:
    result = intent.policy.read(
        (
            "gcloud",
            "pubsub",
            "topics",
            "list",
            f"--project={intent.context.project_id}",
            f"--filter=name={intent.resource_name}",
            "--format=json",
        )
    )
    if result.returncode != 0:
        code = "topic-reconcile-failed"
        raise ProvisioningError(code)
    return parse_topic_list(result.stdout)


def prepare_topic(
    context: GcpContext,
    topic: str,
    policy: ReconciliationPolicy = DEFAULT_RECONCILIATION_POLICY,
) -> TopicRollbackIntent:
    """Prove exact topic absence before registering rollback ownership."""
    intent = TopicRollbackIntent(context, topic, policy)
    if _topic_list(intent):
        code = "topic-name-conflict"
        raise ProvisioningError(code)
    return intent


def create_topic(intent: TopicRollbackIntent) -> None:
    """Create and read back the exact topic after any command result."""
    result = intent.policy.read(
        (
            "gcloud",
            "pubsub",
            "topics",
            "create",
            intent.topic,
            f"--project={intent.context.project_id}",
        )
    )
    visible = intent.policy.poll(
        lambda: _topic_list(intent),
        lambda snapshots: len(snapshots) == 1 and snapshots[0].name == intent.resource_name,
    )
    if result.returncode != 0:
        code = "topic-create-failed"
        raise ProvisioningError(code)
    if visible is None:
        code = "topic-reconcile-failed"
        raise ProvisioningError(code)


def cleanup_topic(intent: TopicRollbackIntent) -> bool:
    """Delete only the exact topic owned by the registered intent."""
    try:
        visible = intent.policy.poll(
            lambda: _topic_list(intent),
            lambda snapshots: len(snapshots) == 1 and snapshots[0].name == intent.resource_name,
        )
    except ProvisioningError:
        return False
    if visible is None:
        return False
    _ = intent.policy.read(
        (
            "gcloud",
            "pubsub",
            "topics",
            "delete",
            intent.topic,
            f"--project={intent.context.project_id}",
            "--quiet",
        )
    )
    try:
        absent = intent.policy.poll(
            lambda: _topic_list(intent),
            lambda snapshots: snapshots == (),
            confirmations=2,
        )
    except ProvisioningError:
        return False
    return absent is not None


def _budget_list(intent: BudgetRollbackIntent) -> tuple[BudgetSnapshot, ...]:
    result = intent.policy.read(
        (
            "gcloud",
            "billing",
            "budgets",
            "list",
            f"--billing-account={intent.context.billing_account_id}",
            "--format=json",
        )
    )
    if result.returncode != 0:
        code = "budget-reconcile-failed"
        raise ProvisioningError(code)
    return parse_budget_list(result.stdout)


def prepare_budget(
    context: GcpContext,
    topic: str,
    policy: ReconciliationPolicy = DEFAULT_RECONCILIATION_POLICY,
) -> BudgetRollbackIntent:
    """Prove unique display-name absence before registering rollback ownership."""
    intent = BudgetRollbackIntent(context, topic, policy)
    if any(snapshot.display_name == topic for snapshot in _budget_list(intent)):
        code = "budget-name-conflict"
        raise ProvisioningError(code)
    return intent


def create_budget(intent: BudgetRollbackIntent) -> BudgetCleanupTarget:
    """Create a budget and reconcile its server-assigned ID by exact contract."""
    result = intent.policy.read(
        (
            "gcloud",
            "billing",
            "budgets",
            "create",
            f"--billing-account={intent.context.billing_account_id}",
            f"--display-name={intent.display_name}",
            "--budget-amount=1USD",
            f"--notifications-rule-pubsub-topic={intent.topic_resource}",
            f"--filter-projects={intent.project_resource}",
            "--format=value(name)",
        )
    )
    targets = intent.policy.poll(
        lambda: tuple(
            target
            for snapshot in _budget_list(intent)
            if snapshot.display_name == intent.display_name
            if (target := intent.target(snapshot)) is not None
        ),
        lambda candidates: len(candidates) == 1,
    )
    if result.returncode != 0:
        code = "budget-create-failed"
        raise ProvisioningError(code)
    response_target = parse_budget_target(
        result.stdout.strip(), intent.context, intent.display_name
    )
    if targets is None or targets[0] != response_target:
        code = "budget-reconcile-failed"
        raise ProvisioningError(code)
    return response_target


def cleanup_budget(intent: BudgetRollbackIntent) -> bool:
    """Delete the sole exact account-bound budget; fail closed otherwise."""
    try:
        targets = intent.policy.poll(
            lambda: tuple(
                target
                for snapshot in _budget_list(intent)
                if snapshot.display_name == intent.display_name
                if (target := intent.target(snapshot)) is not None
            ),
            lambda candidates: len(candidates) == 1,
        )
    except ProvisioningError:
        return False
    if targets is None:
        return False
    _ = intent.policy.read(
        (
            "gcloud",
            "billing",
            "budgets",
            "delete",
            targets[0].resource_name,
            "--quiet",
        )
    )
    try:
        absent = intent.policy.poll(
            lambda: _budget_list(intent),
            lambda snapshots: (
                not any(snapshot.display_name == intent.display_name for snapshot in snapshots)
            ),
            confirmations=2,
        )
    except ProvisioningError:
        return False
    return absent is not None
