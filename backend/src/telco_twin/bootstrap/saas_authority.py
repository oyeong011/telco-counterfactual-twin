"""Cloudflare Pages and Neon GET authority composition."""

from __future__ import annotations

import os

from telco_twin.bootstrap.cloudflare_probe import (
    CloudflareContext,
    CloudflareProbeReceipt,
)
from telco_twin.bootstrap.neon_probe import NeonContext, NeonProbeReceipt
from telco_twin.bootstrap.preflight_contract import (
    CLOUDFLARE_PERMISSIONS,
    NEON_PERMISSIONS,
    AuthorityReceipt,
    CleanupStatus,
    ProviderResult,
    receipt_for,
)
from telco_twin.bootstrap.probe_errors import ProviderProbeError
from telco_twin.bootstrap.provider_adapters import (
    ProviderAdapters,
    missing_prerequisites,
)
from telco_twin.bootstrap.provider_results import (
    ProviderFacts,
    blocked_provider,
    make_provider,
)


def cloudflare_authority(
    context: CloudflareContext,
    receipt: CloudflareProbeReceipt,
) -> AuthorityReceipt:
    """Build stable account, credential, and read-operation evidence."""
    return AuthorityReceipt(
        identities=(f"accounts/{receipt.account_id}", "pages/projects"),
        request_hashes=tuple(
            receipt_for("cloudflare-request", operation)
            for operation in ("token-verify", "account-get", "pages-list")
        ),
        response_hashes=(
            receipt_for("cloudflare-token", context.api_token),
            receipt_for(
                "cloudflare-read-statuses",
                *(str(status) for status in receipt.http_statuses[:3]),
            ),
        ),
        command_hashes=(receipt_for("wrangler", "pages", "deploy"),),
    )


def neon_authority(receipt: NeonProbeReceipt) -> AuthorityReceipt:
    """Build stable organization and GET-operation evidence."""
    return AuthorityReceipt(
        identities=(f"organizations/{receipt.org_id}", "projects"),
        request_hashes=(
            receipt_for("neon-request", "organization-get", receipt.org_id),
            receipt_for("neon-request", "projects-list", receipt.org_id),
        ),
        response_hashes=(receipt.evidence,),
        command_hashes=(),
    )


def probe_cloudflare_authority(
    adapters: ProviderAdapters,
    source_sha: str,
) -> ProviderResult:
    """Run the reversible Pages probe only when both credential and CLI exist."""
    blockers = missing_prerequisites(
        adapters,
        "wrangler",
        ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"),
    )
    if blockers:
        return blocked_provider("cloudflare", blockers)
    wrangler = adapters.which("wrangler")
    if wrangler is None:
        return blocked_provider("cloudflare", ("missing-command:wrangler",))
    context = CloudflareContext(
        account_id=os.environ["CLOUDFLARE_ACCOUNT_ID"],
        api_token=os.environ["CLOUDFLARE_API_TOKEN"],
        source_sha=source_sha,
        wrangler_command=wrangler,
    )
    try:
        receipt = adapters.cloudflare(context)
    except ProviderProbeError as error:
        return blocked_provider("cloudflare", (error.code,))
    return make_provider(
        ProviderFacts(
            provider="cloudflare",
            granted_permissions=frozenset(CLOUDFLARE_PERMISSIONS),
            blockers=(),
            cleanup=CleanupStatus.RESTORED,
            seed=receipt.evidence,
            authority=cloudflare_authority(context, receipt),
        )
    )


def probe_neon_authority(adapters: ProviderAdapters) -> ProviderResult:
    """Run only the Task 1 GET organization/projects authority probe."""
    blockers = missing_prerequisites(adapters, None, ("NEON_API_KEY", "NEON_ORG_ID"))
    if blockers:
        return blocked_provider("neon", blockers)
    context = NeonContext(
        org_id=os.environ["NEON_ORG_ID"],
        api_key=os.environ["NEON_API_KEY"],
    )
    try:
        receipt = adapters.neon(context)
    except ProviderProbeError as error:
        return blocked_provider("neon", (error.code,))
    return make_provider(
        ProviderFacts(
            provider="neon",
            granted_permissions=frozenset(NEON_PERMISSIONS),
            blockers=(),
            cleanup=CleanupStatus.CLEAN,
            seed=receipt.evidence,
            authority=neon_authority(receipt),
        )
    )
