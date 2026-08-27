"""Idempotent GitHub Actions WIF configuration with rollback snapshots."""

from __future__ import annotations

import secrets
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from telco_twin.bootstrap.gcp_commands import (
    GcpContext,
    ProvisioningError,
    require_gcloud,
)
from telco_twin.bootstrap.gcp_persistent import (
    POOL_ID,
    PROVIDER_ID,
    ensure_persistent,
)
from telco_twin.bootstrap.gcp_resource_probe import run_temporary_probes
from telco_twin.bootstrap.gcp_rollback import restore_persistent
from telco_twin.bootstrap.preflight_contract import receipt_for

REQUIRED_SERVICES = (
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "pubsub.googleapis.com",
    "cloudbilling.googleapis.com",
    "billingbudgets.googleapis.com",
)


class CleanupReceipt(BaseModel):
    """Cleanup facts for reversible preflight resources."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    cleanup_complete: bool
    temporary_resources: tuple[str, ...]
    restored_bindings: bool


class WifApplyReceipt(BaseModel):
    """Secret-free result of persistent WIF and temporary probes."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ready"]
    project_id: str
    project_number: str = Field(pattern=r"^[0-9]+$")
    pool_id: Literal["github-actions"]
    provider_id: Literal["github-oidc"]
    deploy_service_account: str
    cleanup: CleanupReceipt
    evidence: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


def apply_wif(context: GcpContext) -> WifApplyReceipt:
    """Apply WIF and retain it only after all temporary probes clean up."""
    account = require_gcloud(
        ("gcloud", "auth", "list", "--filter=status:ACTIVE", "--format=value(account)"),
        "gcloud-auth-missing",
    )
    if not account:
        code = "gcloud-auth-missing"
        raise ProvisioningError(code)
    _ = require_gcloud(
        (
            "gcloud",
            "services",
            "enable",
            *REQUIRED_SERVICES,
            f"--project={context.project_id}",
            "--quiet",
        ),
        "service-enable-failed",
    )
    state = ensure_persistent(context)
    try:
        probe = run_temporary_probes(context, state.service_account, secrets.token_hex(6))
    except ProvisioningError:
        if not restore_persistent(context, state):
            code = "persistent-rollback-failed"
            raise ProvisioningError(code) from None
        raise
    return WifApplyReceipt(
        status="ready",
        project_id=context.project_id,
        project_number=context.project_number,
        pool_id=POOL_ID,
        provider_id=PROVIDER_ID,
        deploy_service_account=state.service_account,
        cleanup=CleanupReceipt(
            cleanup_complete=probe.cleanup_complete,
            temporary_resources=(),
            restored_bindings=probe.restored_bindings,
        ),
        evidence=receipt_for(
            context.project_id,
            context.project_number,
            context.owner_id,
            "wif-ready",
        ),
    )
