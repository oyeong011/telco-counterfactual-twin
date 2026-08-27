"""Transactional temporary Pub/Sub topic and Budget API mutations."""

from __future__ import annotations

from telco_twin.bootstrap import gcp_commands
from telco_twin.bootstrap.gcp_commands import GcpContext, ProvisioningError
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
    result = gcp_commands.run_gcloud(
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


def prepare_topic(context: GcpContext, topic: str) -> TopicRollbackIntent:
    """Prove exact topic absence before registering rollback ownership."""
    intent = TopicRollbackIntent(context, topic)
    if _topic_list(intent):
        code = "topic-name-conflict"
        raise ProvisioningError(code)
    return intent


def create_topic(intent: TopicRollbackIntent) -> None:
    """Create and read back the exact topic after any command result."""
    result = gcp_commands.run_gcloud(
        (
            "gcloud",
            "pubsub",
            "topics",
            "create",
            intent.topic,
            f"--project={intent.context.project_id}",
        )
    )
    snapshots = _topic_list(intent)
    exact = tuple(snapshot for snapshot in snapshots if snapshot.name == intent.resource_name)
    if result.returncode != 0:
        code = "topic-create-failed"
        raise ProvisioningError(code)
    if len(snapshots) != 1 or len(exact) != 1:
        code = "topic-reconcile-failed"
        raise ProvisioningError(code)


def cleanup_topic(intent: TopicRollbackIntent) -> bool:
    """Delete only the exact topic owned by the registered intent."""
    try:
        snapshots = _topic_list(intent)
    except ProvisioningError:
        return False
    if not snapshots:
        return True
    if len(snapshots) != 1 or snapshots[0].name != intent.resource_name:
        return False
    _ = gcp_commands.run_gcloud(
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
        return _topic_list(intent) == ()
    except ProvisioningError:
        return False


def _budget_list(intent: BudgetRollbackIntent) -> tuple[BudgetSnapshot, ...]:
    result = gcp_commands.run_gcloud(
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


def prepare_budget(context: GcpContext, topic: str) -> BudgetRollbackIntent:
    """Prove unique display-name absence before registering rollback ownership."""
    intent = BudgetRollbackIntent(context, topic)
    if any(snapshot.display_name == topic for snapshot in _budget_list(intent)):
        code = "budget-name-conflict"
        raise ProvisioningError(code)
    return intent


def create_budget(intent: BudgetRollbackIntent) -> BudgetCleanupTarget:
    """Create a budget and reconcile its server-assigned ID by exact contract."""
    result = gcp_commands.run_gcloud(
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
    snapshots = _budget_list(intent)
    targets = tuple(
        target
        for snapshot in snapshots
        if snapshot.display_name == intent.display_name
        if (target := intent.target(snapshot)) is not None
    )
    if result.returncode != 0:
        code = "budget-create-failed"
        raise ProvisioningError(code)
    response_target = parse_budget_target(
        result.stdout.strip(), intent.context, intent.display_name
    )
    if len(targets) != 1 or targets[0] != response_target:
        code = "budget-reconcile-failed"
        raise ProvisioningError(code)
    return response_target


def cleanup_budget(intent: BudgetRollbackIntent) -> bool:
    """Delete the sole exact account-bound budget; fail closed otherwise."""
    try:
        snapshots = _budget_list(intent)
    except ProvisioningError:
        return False
    same_name = tuple(
        snapshot for snapshot in snapshots if snapshot.display_name == intent.display_name
    )
    targets = tuple(
        target for snapshot in same_name if (target := intent.target(snapshot)) is not None
    )
    if len(same_name) != 1 or len(targets) != 1:
        return False
    _ = gcp_commands.run_gcloud(
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
        after = _budget_list(intent)
    except ProvisioningError:
        return False
    return not any(snapshot.display_name == intent.display_name for snapshot in after)
