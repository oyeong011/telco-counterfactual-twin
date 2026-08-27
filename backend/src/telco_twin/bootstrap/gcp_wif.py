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
from telco_twin.bootstrap.gcp_persistent import ensure_persistent
from telco_twin.bootstrap.gcp_persistent_contract import (
    POOL_ID,
    PROVIDER_ID,
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


class TemporaryProbeReceipt(BaseModel):
    """Non-secret identifiers and hashes from reversible GCP resource probes."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    topic_resource: str = Field(min_length=1)
    budget_resource: str = Field(min_length=1)
    budget_schema_version: Literal["1.0"]
    publisher_policy_evidence: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    deny_exchange_evidence: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


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
    temporary_probe: TemporaryProbeReceipt
    deny_exchange_evidence: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
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
        temporary_probe=TemporaryProbeReceipt(
            topic_resource=probe.topic_resource,
            budget_resource=probe.budget_resource,
            budget_schema_version=probe.budget_schema_version,
            publisher_policy_evidence=probe.publisher_policy_evidence,
            deny_exchange_evidence=probe.deny_exchange_evidence,
        ),
        deny_exchange_evidence=probe.deny_exchange_evidence,
        evidence=receipt_for(
            context.project_id,
            context.project_number,
            context.owner_id,
            probe.topic_resource,
            probe.budget_resource,
            probe.publisher_policy_evidence,
            probe.deny_exchange_evidence,
            "wif-ready",
        ),
    )
