"""Deploy service-account discovery, creation, and IAM snapshot boundary."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, ClassVar, Protocol

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from telco_twin.bootstrap.gcp_commands import (
    GcpContext,
    ProvisioningError,
    require_gcloud,
)
from telco_twin.bootstrap.gcp_iam_contract import IamPolicy, parse_iam_policy
from telco_twin.bootstrap.gcp_ownership import OperationOwnership, RunOwnership
from telco_twin.bootstrap.gcp_reconciliation import (
    DEFAULT_RECONCILIATION_POLICY,
    ReconciliationPolicy,
)

if TYPE_CHECKING:
    from telco_twin.bootstrap.gcp_binding import BindingRollbackIntent

SERVICE_ACCOUNT_ID = "skt-portfolio-deployer"
SERVICE_ACCOUNT_DISPLAY_NAME = "SKT Portfolio Deployer"


class ServiceAccountProjection(BaseModel):
    """Service-account list projection used for exact identity reconciliation."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    name: str
    unique_id: str = Field(alias="uniqueId", min_length=1)
    email: str
    display_name: str = Field(alias="displayName")
    description: str = ""


SERVICE_ACCOUNTS_ADAPTER = TypeAdapter(tuple[ServiceAccountProjection, ...])


@dataclass(frozen=True, slots=True)
class ServiceAccountCreateIntent:
    """Exact service-account rollback ownership registered before create."""

    context: GcpContext
    service_account: str
    ownership: OperationOwnership
    policy: ReconciliationPolicy = DEFAULT_RECONCILIATION_POLICY

    @property
    def resource_name(self) -> str:
        """Return the exact service-account resource identity."""
        return f"projects/{self.context.project_id}/serviceAccounts/{self.service_account}"

    def accounts(self) -> tuple[ServiceAccountProjection, ...] | None:
        """List exact-email candidates under the expected project."""
        result = self.policy.read(
            (
                "gcloud",
                "iam",
                "service-accounts",
                "list",
                f"--project={self.context.project_id}",
                f"--filter=email={self.service_account}",
                "--format=json",
            )
        )
        if result.returncode != 0:
            return None
        try:
            return SERVICE_ACCOUNTS_ADAPTER.validate_json(result.stdout)
        except ValidationError:
            return None

    def matches(self, account: ServiceAccountProjection) -> bool:
        """Require the identity and fingerprint assigned by this preflight."""
        return (
            account.name == self.resource_name
            and account.email == self.service_account
            and account.display_name == SERVICE_ACCOUNT_DISPLAY_NAME
            and account.description == self.ownership.marker
        )

    def rollback(self) -> bool:
        """Read back and delete only the exact account created by this intent."""
        visible = self.policy.poll(
            self.accounts,
            lambda accounts: (
                accounts is not None and len(accounts) == 1 and self.matches(accounts[0])
            ),
        )
        if visible is None:
            return False
        account = visible[0]
        _ = self.policy.read(
            (
                "gcloud",
                "iam",
                "service-accounts",
                "delete",
                account.unique_id,
                "--quiet",
            )
        )
        absent = self.policy.poll(
            self.accounts,
            lambda accounts: accounts == (),
            confirmations=2,
        )
        return absent is not None


class ServiceAccountState(Protocol):
    """Service-account identity with a variant-specific rollback operation."""

    @property
    def service_account(self) -> str:
        """Return the deploy service-account email."""
        ...

    def rollback(self) -> bool:
        """Restore or delete the service account according to its initial state."""
        ...

    def register_pending_binding(self, intent: BindingRollbackIntent) -> ServiceAccountState:
        """Register a binding mutation before its dispatch."""
        ...


@dataclass(frozen=True, slots=True)
class ExistingServiceAccountSnapshot:
    """IAM policy captured from a pre-existing service account."""

    service_account: str
    iam_policy: str
    policy: ReconciliationPolicy = DEFAULT_RECONCILIATION_POLICY
    pending_bindings: tuple[BindingRollbackIntent, ...] = ()

    def register_pending_binding(
        self,
        intent: BindingRollbackIntent,
    ) -> ExistingServiceAccountSnapshot:
        """Register one operation-owned binding before its dispatch."""
        return replace(self, pending_bindings=(*self.pending_bindings, intent))

    def _current_policy(self) -> IamPolicy | None:
        result = self.policy.read(
            (
                "gcloud",
                "iam",
                "service-accounts",
                "get-iam-policy",
                self.service_account,
                "--format=json",
            )
        )
        if result.returncode != 0:
            return None
        try:
            return parse_iam_policy(result.stdout)
        except ProvisioningError:
            return None

    def rollback(self) -> bool:
        """Restore the preflight IAM policy snapshot."""
        try:
            original_policy = parse_iam_policy(self.iam_policy)
        except ProvisioningError:
            return False
        if not self.pending_bindings:
            current = self.policy.poll(
                self._current_policy,
                lambda candidate: candidate == original_policy,
                confirmations=2,
            )
            return current is not None
        restored = True
        for intent in reversed(self.pending_bindings):
            restored &= intent.rollback()
        current = self.policy.poll(
            self._current_policy,
            lambda candidate: candidate == original_policy,
            confirmations=2,
        )
        return bool(current is not None and restored)


@dataclass(frozen=True, slots=True)
class CreatedServiceAccountSnapshot:
    """A service account created by the current preflight."""

    intent: ServiceAccountCreateIntent

    @property
    def service_account(self) -> str:
        """Return the exact created service-account email."""
        return self.intent.service_account

    def rollback(self) -> bool:
        """Delete the service account created by the failed preflight."""
        return self.intent.rollback()

    def register_pending_binding(
        self,
        intent: BindingRollbackIntent,
    ) -> CreatedServiceAccountSnapshot:
        """Account deletion already owns all bindings created beneath it."""
        _ = intent
        return self


def ensure_service_account(
    context: GcpContext,
    policy: ReconciliationPolicy = DEFAULT_RECONCILIATION_POLICY,
    ownership: OperationOwnership | None = None,
) -> ServiceAccountState:
    """Describe first, snapshot existing IAM, or create without a nonexistent policy read."""
    service_account = f"{SERVICE_ACCOUNT_ID}@{context.project_id}.iam.gserviceaccount.com"
    active_ownership = (
        RunOwnership.generate().for_operation("service-account") if ownership is None else ownership
    )
    described = policy.read(("gcloud", "iam", "service-accounts", "describe", service_account))
    intent = ServiceAccountCreateIntent(context, service_account, active_ownership, policy)
    accounts = intent.accounts()
    if accounts is None:
        code = "service-account-list-failed"
        raise ProvisioningError(code)
    if len(accounts) > 1:
        code = "service-account-identity-ambiguous"
        raise ProvisioningError(code)
    if described.returncode == 0 or accounts:
        iam_policy = require_gcloud(
            (
                "gcloud",
                "iam",
                "service-accounts",
                "get-iam-policy",
                service_account,
                "--format=json",
            ),
            "service-account-policy-snapshot-failed",
        )
        return ExistingServiceAccountSnapshot(
            service_account=service_account,
            iam_policy=iam_policy,
            policy=policy,
        )
    result = policy.read(
        (
            "gcloud",
            "iam",
            "service-accounts",
            "create",
            SERVICE_ACCOUNT_ID,
            f"--project={context.project_id}",
            f"--display-name={SERVICE_ACCOUNT_DISPLAY_NAME}",
            f"--description={active_ownership.marker}",
            "--quiet",
        )
    )
    created = policy.poll(
        intent.accounts,
        lambda accounts: (
            accounts is not None and len(accounts) == 1 and intent.matches(accounts[0])
        ),
    )
    reconciled = created is not None
    if result.returncode != 0 or not reconciled:
        if not intent.rollback():
            code = "service-account-ownership-conflict"
            raise ProvisioningError(code)
        code = "service-account-create-failed"
        raise ProvisioningError(code)
    return CreatedServiceAccountSnapshot(intent=intent)
