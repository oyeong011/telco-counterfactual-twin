"""Deploy service-account discovery, creation, and IAM snapshot boundary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol

from telco_twin.bootstrap.gcp_commands import (
    GcpContext,
    attempt_gcloud,
    require_gcloud,
    run_gcloud,
)


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
        with TemporaryDirectory(prefix="twin-wif-rollback-") as temp_dir:
            policy_path = Path(temp_dir) / "policy.json"
            _ = policy_path.write_text(self.iam_policy, encoding="utf-8")
            return attempt_gcloud(
                (
                    "gcloud",
                    "iam",
                    "service-accounts",
                    "set-iam-policy",
                    self.service_account,
                    str(policy_path),
                )
            )


@dataclass(frozen=True, slots=True)
class CreatedServiceAccountSnapshot:
    """A service account created by the current preflight."""

    service_account: str

    def rollback(self) -> bool:
        """Delete the service account created by the failed preflight."""
        return attempt_gcloud(
            (
                "gcloud",
                "iam",
                "service-accounts",
                "delete",
                self.service_account,
                "--quiet",
            )
        )


def ensure_service_account(context: GcpContext) -> ServiceAccountState:
    """Describe first, snapshot existing IAM, or create without a nonexistent policy read."""
    service_account = f"skt-portfolio-deployer@{context.project_id}.iam.gserviceaccount.com"
    described = run_gcloud(("gcloud", "iam", "service-accounts", "describe", service_account))
    if described.returncode == 0:
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
    _ = require_gcloud(
        (
            "gcloud",
            "iam",
            "service-accounts",
            "create",
            "skt-portfolio-deployer",
            f"--project={context.project_id}",
            "--quiet",
        ),
        "service-account-create-failed",
    )
    return CreatedServiceAccountSnapshot(service_account=service_account)
