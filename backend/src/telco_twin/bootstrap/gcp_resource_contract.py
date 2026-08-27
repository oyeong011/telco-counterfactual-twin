"""Typed Budget API and Pub/Sub IAM contracts for reversible probes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from telco_twin.bootstrap.gcp_commands import ProvisioningError

if TYPE_CHECKING:
    from telco_twin.bootstrap.gcp_commands import GcpContext

PUBLISHER_ROLE = "roles/pubsub.publisher"
PUBLISHER_MEMBER = "serviceAccount:billing-budget-alert@system.gserviceaccount.com"
PROBE_PREFIX: Final = "twin-preflight-"


@dataclass(frozen=True, slots=True)
class BudgetCleanupTarget:
    """Account-bound budget identity and unique probe record."""

    resource_name: str
    billing_account_id: str
    display_name: str
    topic_resource: str
    project_resource: str

    def is_owned_by(self, context: GcpContext, topic: str) -> bool:
        """Recheck account, resource syntax, and unique probe identity."""
        resource_pattern = (
            rf"^billingAccounts/{re.escape(context.billing_account_id)}/"
            r"budgets/[^/]+$"
        )
        return (
            re.fullmatch(resource_pattern, self.resource_name) is not None
            and self.billing_account_id == context.billing_account_id
            and self.display_name == topic
            and topic.startswith(PROBE_PREFIX)
            and self.topic_resource == f"projects/{context.project_id}/topics/{topic}"
            and self.project_resource == f"projects/{context.project_number}"
        )


class IamBinding(BaseModel):
    """Pub/Sub IAM binding projection."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    role: str
    members: tuple[str, ...] = ()


class IamPolicy(BaseModel):
    """Pub/Sub IAM policy projection."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    bindings: tuple[IamBinding, ...]


class BudgetNotificationsRule(BaseModel):
    """Budget notification schema projection."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    schema_version: Literal["1.0"] = Field(alias="schemaVersion")
    pubsub_topic: str = Field(alias="pubsubTopic")


class BudgetFilter(BaseModel):
    """Budget filter projection bound to the probe project."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    projects: tuple[str, ...]


class BudgetSnapshot(BaseModel):
    """Created Budget API resource projection."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    name: str
    display_name: str = Field(alias="displayName")
    budget_filter: BudgetFilter = Field(alias="budgetFilter")
    notifications_rule: BudgetNotificationsRule = Field(alias="notificationsRule")


def parse_budget_target(
    name: str,
    context: GcpContext,
    probe_name: str,
) -> BudgetCleanupTarget:
    """Parse the create result into an account-bound cleanup target."""
    target = BudgetCleanupTarget(
        resource_name=name,
        billing_account_id=context.billing_account_id,
        display_name=probe_name,
        topic_resource=f"projects/{context.project_id}/topics/{probe_name}",
        project_resource=f"projects/{context.project_number}",
    )
    if not target.is_owned_by(context, probe_name):
        code = "invalid-budget-resource-name"
        raise ProvisioningError(code)
    return target


def parse_publisher_policy(policy: str) -> IamPolicy:
    """Require the exact Cloud Billing system publisher edge."""
    try:
        parsed = IamPolicy.model_validate_json(policy)
    except ValidationError:
        code = "billing-publisher-policy-invalid"
        raise ProvisioningError(code) from None
    has_edge = any(
        binding.role == PUBLISHER_ROLE and PUBLISHER_MEMBER in binding.members
        for binding in parsed.bindings
    )
    if not has_edge:
        code = "billing-publisher-edge-missing"
        raise ProvisioningError(code)
    return parsed


def parse_budget(
    snapshot: str,
    target: BudgetCleanupTarget,
) -> BudgetSnapshot:
    """Require the complete created budget identity and notification edge."""
    try:
        budget = BudgetSnapshot.model_validate_json(snapshot)
    except ValidationError:
        code = "budget-schema-version-mismatch"
        raise ProvisioningError(code) from None
    identity_matches = (
        budget.name == target.resource_name
        and budget.display_name == target.display_name
        and budget.notifications_rule.pubsub_topic == target.topic_resource
        and budget.budget_filter.projects == (target.project_resource,)
    )
    if not identity_matches:
        code = "budget-probe-identity-mismatch"
        raise ProvisioningError(code)
    return budget
