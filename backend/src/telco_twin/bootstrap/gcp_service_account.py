"""Deploy service-account discovery, creation, and IAM snapshot boundary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import ClassVar, Protocol

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from telco_twin.bootstrap.gcp_commands import (
    GcpContext,
    ProvisioningError,
    require_gcloud,
    run_gcloud,
)
from telco_twin.bootstrap.gcp_iam_contract import parse_iam_policy

SERVICE_ACCOUNT_ID = "skt-portfolio-deployer"
SERVICE_ACCOUNT_DISPLAY_NAME = "SKT Portfolio Deployer"


class ServiceAccountProjection(BaseModel):
    """Service-account list projection used for exact identity reconciliation."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    name: str
    email: str
    display_name: str = Field(alias="displayName")


SERVICE_ACCOUNTS_ADAPTER = TypeAdapter(tuple[ServiceAccountProjection, ...])


@dataclass(frozen=True, slots=True)
class ServiceAccountCreateIntent:
    """Exact service-account rollback ownership registered before create."""

    context: GcpContext
    service_account: str

    @property
    def resource_name(self) -> str:
        """Return the exact service-account resource identity."""
        return f"projects/{self.context.project_id}/serviceAccounts/{self.service_account}"

    def accounts(self) -> tuple[ServiceAccountProjection, ...] | None:
        """List exact-email candidates under the expected project."""
        result = run_gcloud(
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
        )

    def rollback(self) -> bool:
        """Read back and delete only the exact account created by this intent."""
        accounts = self.accounts()
        if accounts is None:
            return False
        if not accounts:
            return True
        if len(accounts) != 1 or not self.matches(accounts[0]):
            return False
        _ = run_gcloud(
            (
                "gcloud",
                "iam",
                "service-accounts",
                "delete",
                self.service_account,
                "--quiet",
            )
        )
        after = self.accounts()
        return after == ()


class ServiceAccountState(Protocol):
    """Service-account identity with a variant-specific rollback operation."""

    @property
    def service_account(self) -> str:
        """Return the deploy service-account email."""
        ...

    def rollback(self) -> bool:
        """Restore or delete the service account according to its initial state."""
        ...


@dataclass(frozen=True, slots=True)
class ExistingServiceAccountSnapshot:
    """IAM policy captured from a pre-existing service account."""

    service_account: str
    iam_policy: str

    def rollback(self) -> bool:
        """Restore the preflight IAM policy snapshot."""
        current = run_gcloud(
            (
                "gcloud",
                "iam",
                "service-accounts",
                "get-iam-policy",
                self.service_account,
                "--format=json",
            )
        )
        if current.returncode != 0:
            return False
        try:
            current_policy = parse_iam_policy(current.stdout)
            original_policy = parse_iam_policy(self.iam_policy)
        except ProvisioningError:
            return False
        if current_policy == original_policy:
            return True
        with TemporaryDirectory(prefix="twin-wif-rollback-") as temp_dir:
            policy_path = Path(temp_dir) / "policy.json"
            _ = policy_path.write_text(self.iam_policy, encoding="utf-8")
            _ = run_gcloud(
                (
                    "gcloud",
                    "iam",
                    "service-accounts",
                    "set-iam-policy",
                    self.service_account,
                    str(policy_path),
                )
            )
        after = run_gcloud(
            (
                "gcloud",
                "iam",
                "service-accounts",
                "get-iam-policy",
                self.service_account,
                "--format=json",
            )
        )
        if after.returncode != 0:
            return False
        try:
            return parse_iam_policy(after.stdout) == original_policy
        except ProvisioningError:
            return False


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


def ensure_service_account(context: GcpContext) -> ServiceAccountState:
    """Describe first, snapshot existing IAM, or create without a nonexistent policy read."""
    service_account = f"{SERVICE_ACCOUNT_ID}@{context.project_id}.iam.gserviceaccount.com"
    described = run_gcloud(("gcloud", "iam", "service-accounts", "describe", service_account))
    intent = ServiceAccountCreateIntent(context, service_account)
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
        )
    result = run_gcloud(
        (
            "gcloud",
            "iam",
            "service-accounts",
            "create",
            SERVICE_ACCOUNT_ID,
            f"--project={context.project_id}",
            f"--display-name={SERVICE_ACCOUNT_DISPLAY_NAME}",
            "--quiet",
        )
    )
    created = intent.accounts()
    reconciled = created is not None and len(created) == 1 and intent.matches(created[0])
    if result.returncode != 0 or not reconciled:
        if not intent.rollback():
            code = "service-account-rollback-failed"
            raise ProvisioningError(code)
        code = "service-account-create-failed"
        raise ProvisioningError(code)
    return CreatedServiceAccountSnapshot(intent=intent)
