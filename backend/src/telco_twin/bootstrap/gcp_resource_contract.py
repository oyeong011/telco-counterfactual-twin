"""Typed Budget API and Pub/Sub IAM contracts for reversible probes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Final

from pydantic import AliasPath, BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from telco_twin.bootstrap.gcp_commands import ProvisioningError
from telco_twin.bootstrap.gcp_iam_contract import IamPolicy, parse_iam_policy
from telco_twin.bootstrap.gcp_persistent_contract import ISSUER, MAPPING

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


class TemporaryProviderSnapshot(BaseModel):
    """Temporary provider identity returned by an exact-parent list."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    name: str
    issuer: str = Field(validation_alias=AliasPath("oidc", "issuerUri"))
    mapping: dict[str, str] = Field(alias="attributeMapping")
    condition: str = Field(alias="attributeCondition")


class TopicSnapshot(BaseModel):
    """Pub/Sub topic identity returned by an exact-project list."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    name: str


@dataclass(frozen=True, slots=True)
class ProviderRollbackIntent:
    """Expected temporary provider registered before create dispatch."""

    context: GcpContext
    provider_id: str
    condition: str

    @property
    def resource_name(self) -> str:
        """Return the exact provider resource identity."""
        return (
            f"projects/{self.context.project_number}/locations/global/"
            f"workloadIdentityPools/github-actions/providers/{self.provider_id}"
        )

    def matches(self, snapshot: TemporaryProviderSnapshot) -> bool:
        """Require the exact task-created provider configuration."""
        expected_mapping: dict[str, str] = {}
        for item in MAPPING.split(","):
            key, value = item.split("=", 1)
            expected_mapping[key] = value
        return (
            snapshot.name == self.resource_name
            and snapshot.issuer == ISSUER
            and snapshot.mapping == expected_mapping
            and snapshot.condition == self.condition
        )


@dataclass(frozen=True, slots=True)
class TopicRollbackIntent:
    """Expected temporary topic registered before create dispatch."""

    context: GcpContext
    topic: str

    @property
    def resource_name(self) -> str:
        """Return the exact topic resource identity."""
        return f"projects/{self.context.project_id}/topics/{self.topic}"


@dataclass(frozen=True, slots=True)
class BudgetRollbackIntent:
    """Expected server-assigned budget identity registered before create."""

    context: GcpContext
    display_name: str

    @property
    def topic_resource(self) -> str:
        """Return the exact notification topic resource."""
        return f"projects/{self.context.project_id}/topics/{self.display_name}"

    @property
    def project_resource(self) -> str:
        """Return the exact filtered project resource."""
        return f"projects/{self.context.project_number}"

    def target(self, snapshot: BudgetSnapshot) -> BudgetCleanupTarget | None:
        """Return an owned cleanup target only for the complete probe contract."""
        target = BudgetCleanupTarget(
            resource_name=snapshot.name,
            billing_account_id=self.context.billing_account_id,
            display_name=self.display_name,
            topic_resource=self.topic_resource,
            project_resource=self.project_resource,
        )
        if (
            target.is_owned_by(self.context, self.display_name)
            and snapshot.display_name == self.display_name
            and snapshot.notifications_rule.pubsub_topic == self.topic_resource
            and snapshot.budget_filter.projects == (self.project_resource,)
        ):
            return target
        return None


class BudgetNotificationsRule(BaseModel):
    """Budget notification schema projection."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    schema_version: str = Field(alias="schemaVersion")
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


PROVIDER_LIST_ADAPTER = TypeAdapter(tuple[TemporaryProviderSnapshot, ...])
TOPIC_LIST_ADAPTER = TypeAdapter(tuple[TopicSnapshot, ...])
BUDGET_LIST_ADAPTER = TypeAdapter(tuple[BudgetSnapshot, ...])


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
    parsed = parse_iam_policy(policy)
    has_edge = any(
        binding.role == PUBLISHER_ROLE and PUBLISHER_MEMBER in binding.members
        for binding in parsed.bindings
    )
    if not has_edge:
        code = "billing-publisher-edge-missing"
        raise ProvisioningError(code)
    return parsed


def parse_provider_list(raw: str) -> tuple[TemporaryProviderSnapshot, ...]:
    """Parse provider-list JSON without trusting response identities."""
    try:
        return PROVIDER_LIST_ADAPTER.validate_json(raw)
    except ValidationError:
        code = "deny-provider-list-invalid"
        raise ProvisioningError(code) from None


def parse_topic_list(raw: str) -> tuple[TopicSnapshot, ...]:
    """Parse topic-list JSON without trusting response identities."""
    try:
        return TOPIC_LIST_ADAPTER.validate_json(raw)
    except ValidationError:
        code = "topic-list-invalid"
        raise ProvisioningError(code) from None


def parse_budget_list(raw: str) -> tuple[BudgetSnapshot, ...]:
    """Parse Budget API list JSON for exact-account reconciliation."""
    try:
        return BUDGET_LIST_ADAPTER.validate_json(raw)
    except ValidationError:
        code = "budget-list-invalid"
        raise ProvisioningError(code) from None


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
    if budget.notifications_rule.schema_version != "1.0":
        code = "budget-schema-version-mismatch"
        raise ProvisioningError(code)
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
