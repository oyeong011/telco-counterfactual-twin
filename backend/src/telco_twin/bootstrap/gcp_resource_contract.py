"""Typed Budget API and Pub/Sub IAM contracts for reversible probes."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from telco_twin.bootstrap.gcp_commands import ProvisioningError

PUBLISHER_ROLE = "roles/pubsub.publisher"
PUBLISHER_MEMBER = "serviceAccount:billing-budget-alert@system.gserviceaccount.com"


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


class BudgetSnapshot(BaseModel):
    """Created Budget API resource projection."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    name: str
    notifications_rule: BudgetNotificationsRule = Field(alias="notificationsRule")


def require_budget_name(name: str) -> None:
    """Require a fully qualified Budget API resource name."""
    if not name.startswith("billingAccounts/"):
        code = "invalid-budget-resource-name"
        raise ProvisioningError(code)


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


def parse_budget(snapshot: str, expected_name: str) -> BudgetSnapshot:
    """Require the created budget identity and schemaVersion 1.0."""
    try:
        budget = BudgetSnapshot.model_validate_json(snapshot)
    except ValidationError:
        code = "budget-schema-version-mismatch"
        raise ProvisioningError(code) from None
    if budget.name != expected_name:
        code = "budget-resource-name-mismatch"
        raise ProvisioningError(code)
    return budget
