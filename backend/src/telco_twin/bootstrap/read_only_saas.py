"""Side-effect-free Cloudflare and Neon authority revalidation."""

from __future__ import annotations

import os

import httpx2

from telco_twin.bootstrap.cloudflare_contract import (
    AccountEnvelope,
    ProjectsEnvelope,
    TokenEnvelope,
    parse_response,
)
from telco_twin.bootstrap.http_client import create_http_client
from telco_twin.bootstrap.neon_probe import NeonContext
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
    DEFAULT_ADAPTERS,
    missing_prerequisites,
)
from telco_twin.bootstrap.provider_results import (
    ProviderFacts,
    blocked_provider,
    make_provider,
)
from telco_twin.bootstrap.saas_authority import neon_authority


def probe_cloudflare_read_only() -> ProviderResult:
    """Revalidate the exact token, account, and Pages-list authority."""
    blockers = missing_prerequisites(
        DEFAULT_ADAPTERS,
        "wrangler",
        ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"),
    )
    if blockers:
        return blocked_provider("cloudflare", blockers)
    account_id = os.environ["CLOUDFLARE_ACCOUNT_ID"]
    api_token = os.environ["CLOUDFLARE_API_TOKEN"]
    statuses: list[int] = []
    try:
        with create_http_client(
            "https://api.cloudflare.com/client/v4/",
            {"Authorization": f"Bearer {api_token}"},
        ) as client:
            token_response = client.get("user/tokens/verify")
            statuses.append(token_response.status_code)
            _ = parse_response(token_response, TokenEnvelope, "token-verify")
            account_response = client.get(f"accounts/{account_id}")
            statuses.append(account_response.status_code)
            account = parse_response(account_response, AccountEnvelope, "account-get")
            projects_response = client.get(f"accounts/{account_id}/pages/projects")
            statuses.append(projects_response.status_code)
            _ = parse_response(projects_response, ProjectsEnvelope, "pages-list")
    except (ProviderProbeError, httpx2.HTTPError) as error:
        return blocked_provider("cloudflare", (type(error).__name__,))
    if account.result.id != account_id:
        return blocked_provider("cloudflare", ("account-id-mismatch",))
    authority = AuthorityReceipt(
        identities=(f"accounts/{account_id}", "pages/projects"),
        request_hashes=tuple(
            receipt_for("cloudflare-request", operation)
            for operation in ("token-verify", "account-get", "pages-list")
        ),
        response_hashes=(
            receipt_for("cloudflare-token", api_token),
            receipt_for(
                "cloudflare-read-statuses",
                *(str(status) for status in statuses),
            ),
        ),
        command_hashes=(receipt_for("wrangler", "pages", "deploy"),),
    )
    return make_provider(
        ProviderFacts(
            provider="cloudflare",
            granted_permissions=frozenset(CLOUDFLARE_PERMISSIONS),
            blockers=(),
            cleanup=CleanupStatus.CLEAN,
            seed=authority.response_hashes[-1],
            authority=authority,
        )
    )


def probe_neon_read_only() -> ProviderResult:
    """Revalidate exact Neon organization and projects GET authority."""
    blockers = missing_prerequisites(
        DEFAULT_ADAPTERS,
        None,
        ("NEON_API_KEY", "NEON_ORG_ID"),
    )
    if blockers:
        return blocked_provider("neon", blockers)
    context = NeonContext(
        org_id=os.environ["NEON_ORG_ID"],
        api_key=os.environ["NEON_API_KEY"],
    )
    try:
        receipt = DEFAULT_ADAPTERS.neon(context)
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
