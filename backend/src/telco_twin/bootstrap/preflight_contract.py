"""Typed and redacted deployment-preflight report contract."""

from __future__ import annotations

import hashlib
import re
from enum import StrEnum
from typing import Annotated, ClassVar, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

type ProviderName = Literal["github", "gcp-project", "gcp-billing", "cloudflare", "neon"]
type Outcome = Literal["deployment-ready", "deployment-blocked"]
type ReceiptHash = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class ProbeStatus(StrEnum):
    """An evidence-backed provider authorization state."""

    READY = "ready"
    BLOCKED = "blocked"


class CleanupStatus(StrEnum):
    """Temporary-resource cleanup state."""

    CLEAN = "clean"
    RESTORED = "restored"
    NOT_CREATED = "not-created"


GITHUB_PERMISSIONS: Final = (
    "repo.public",
    "workflow.read",
    "workflow.dispatch",
    "repo.admin",
)
GCP_PROJECT_PERMISSIONS: Final = (
    "run.services.create",
    "run.services.get",
    "run.services.update",
    "run.services.getIamPolicy",
    "run.services.setIamPolicy",
    "iam.serviceAccounts.create",
    "iam.serviceAccounts.get",
    "iam.serviceAccounts.actAs",
    "iam.serviceAccounts.getIamPolicy",
    "iam.serviceAccounts.setIamPolicy",
    "iam.serviceAccounts.getOpenIdToken",
    "iam.roles.create",
    "iam.roles.get",
    "iam.roles.update",
    "iam.roles.delete",
    "iam.workloadIdentityPools.create",
    "iam.workloadIdentityPools.get",
    "iam.workloadIdentityPools.update",
    "iam.workloadIdentityPools.delete",
    "iam.workloadIdentityPoolProviders.create",
    "iam.workloadIdentityPoolProviders.get",
    "iam.workloadIdentityPoolProviders.update",
    "iam.workloadIdentityPoolProviders.delete",
    "secretmanager.secrets.create",
    "secretmanager.secrets.get",
    "secretmanager.versions.add",
    "secretmanager.versions.access",
    "secretmanager.versions.destroy",
    "secretmanager.secrets.getIamPolicy",
    "secretmanager.secrets.setIamPolicy",
    "serviceusage.services.enable",
    "serviceusage.services.get",
    "serviceusage.services.list",
    "serviceusage.services.use",
    "pubsub.topics.create",
    "pubsub.topics.delete",
    "pubsub.topics.get",
    "pubsub.topics.list",
    "pubsub.topics.publish",
    "pubsub.topics.getIamPolicy",
    "pubsub.topics.setIamPolicy",
    "pubsub.subscriptions.create",
    "pubsub.subscriptions.delete",
    "pubsub.subscriptions.get",
    "pubsub.subscriptions.consume",
    "pubsub.subscriptions.getIamPolicy",
    "pubsub.subscriptions.setIamPolicy",
)
GCP_BILLING_PERMISSIONS: Final = (
    "billing.accounts.get",
    "billing.accounts.getIamPolicy",
    "billing.accounts.getSpendingInformation",
    "billing.budgets.create",
    "billing.budgets.get",
    "billing.budgets.list",
    "billing.budgets.update",
    "billing.resourceAssociations.list",
)
CLOUDFLARE_PERMISSIONS: Final = ("account.settings.read", "pages.edit")
NEON_PERMISSIONS: Final = ("organizations.get", "projects.list")

EXPECTED_PERMISSIONS: Final[dict[ProviderName, tuple[str, ...]]] = {
    "github": GITHUB_PERMISSIONS,
    "gcp-project": GCP_PROJECT_PERMISSIONS,
    "gcp-billing": GCP_BILLING_PERMISSIONS,
    "cloudflare": CLOUDFLARE_PERMISSIONS,
    "neon": NEON_PERMISSIONS,
}
PROVIDER_ORDER: Final[tuple[ProviderName, ...]] = (
    "github",
    "gcp-project",
    "gcp-billing",
    "cloudflare",
    "neon",
)
RECEIPT_PATTERN: Final = r"^sha256:[0-9a-f]{64}$"
MIN_SENSITIVE_VALUE_LENGTH: Final = 8
SECRET_PATTERNS: Final = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\b(?:sk|rk)-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"\bBearer [A-Za-z0-9._-]{20,}\b", flags=re.IGNORECASE),
)


class PermissionResult(BaseModel):
    """One required permission and its redacted receipt."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    permission: str = Field(min_length=1)
    granted: bool
    status: ProbeStatus
    evidence: str = Field(pattern=RECEIPT_PATTERN)

    @model_validator(mode="after")
    def status_matches_grant(self) -> Self:
        """Require the boolean and status enum to describe one fact."""
        if self.granted is (self.status is ProbeStatus.READY):
            return self
        msg = "permission-status-inconsistent"
        raise ValueError(msg)


class AuthorityReceipt(BaseModel):
    """Exact identities and hashed read-only authority exchanges."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    identities: tuple[str, ...] = ()
    request_hashes: tuple[ReceiptHash, ...] = ()
    response_hashes: tuple[ReceiptHash, ...] = ()
    command_hashes: tuple[ReceiptHash, ...] = ()


class ProviderResult(BaseModel):
    """One provider's complete authorization and cleanup result."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    provider: ProviderName
    status: ProbeStatus
    permissions: tuple[PermissionResult, ...]
    blockers: tuple[str, ...]
    cleanup: CleanupStatus
    evidence: str = Field(pattern=RECEIPT_PATTERN)
    authority: AuthorityReceipt = AuthorityReceipt()

    @model_validator(mode="after")
    def provider_is_complete_and_consistent(self) -> Self:
        """Require every named permission and fail closed on mixed claims."""
        expected = set(EXPECTED_PERMISSIONS[self.provider])
        actual = {item.permission for item in self.permissions}
        is_ready = all(item.granted for item in self.permissions)
        status_ready = self.status is ProbeStatus.READY
        cleanup_ready = self.cleanup in {CleanupStatus.CLEAN, CleanupStatus.RESTORED}
        if actual != expected or len(actual) != len(self.permissions):
            msg = "provider-permission-set-incomplete"
            raise ValueError(msg)
        if status_ready and (not is_ready or self.blockers):
            msg = "provider-status-inconsistent"
            raise ValueError(msg)
        if status_ready and not cleanup_ready:
            msg = "provider-cleanup-inconsistent"
            raise ValueError(msg)
        if not status_ready and not self.blockers:
            msg = "provider-status-inconsistent"
            raise ValueError(msg)
        return self


class RepositoryResult(BaseModel):
    """Non-secret repository state bound to the bootstrap commit."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    repository: Literal["oyeong011/telco-counterfactual-twin"]
    local_worktree_clean: Literal[True]
    remote_main_matches_bootstrap: bool
    public_nonfork_main_mit: bool
    workflow_active: bool
    evidence: str = Field(pattern=RECEIPT_PATTERN)


class PreflightReport(BaseModel):
    """Validated deployment-authority report; blocked is a valid outcome."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"]
    generated_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
    bootstrap_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    outcome: Outcome
    cost_control: Literal["preflight-only"]
    repository: RepositoryResult
    providers: tuple[ProviderResult, ...]
    temporary_resources: tuple[str, ...]
    report_evidence: str = Field(pattern=RECEIPT_PATTERN)

    @model_validator(mode="after")
    def outcome_matches_authority(self) -> Self:
        """Permit ready only when every provider and repository proof is ready."""
        if tuple(item.provider for item in self.providers) != PROVIDER_ORDER:
            msg = "report-provider-set-incomplete"
            raise ValueError(msg)
        all_ready = all(item.status is ProbeStatus.READY for item in self.providers)
        repo_ready = (
            self.repository.remote_main_matches_bootstrap
            and self.repository.public_nonfork_main_mit
            and self.repository.workflow_active
        )
        claims_ready = self.outcome == "deployment-ready"
        if claims_ready != (all_ready and repo_ready):
            msg = "report-outcome-inconsistent"
            raise ValueError(msg)
        if self.temporary_resources:
            msg = "temporary-resources-remain"
            raise ValueError(msg)
        return self


def receipt_for(*parts: str) -> str:
    """Hash non-secret probe facts into a stable receipt reference."""
    digest = hashlib.sha256("\0".join(parts).encode()).hexdigest()
    return f"sha256:{digest}"


def contains_secret(text: str, sensitive_values: tuple[str, ...]) -> bool:
    """Return true without echoing the matched credential."""
    pattern_match = any(pattern.search(text) is not None for pattern in SECRET_PATTERNS)
    environment_match = any(
        value in text for value in sensitive_values if len(value) >= MIN_SENSITIVE_VALUE_LENGTH
    )
    return pattern_match or environment_match
