"""Bounded GitHub OIDC and Google STS wire path for denial proof."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, ClassVar, Final
from urllib.parse import urlencode

import httpx2
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from telco_twin.bootstrap.deny_exchange_classifier import (
    classify_deny_exchange,
    verify_deny_provider,
)
from telco_twin.bootstrap.http_client import LIMITS, SOCKET_OPTIONS

if TYPE_CHECKING:
    from telco_twin.bootstrap.deny_exchange_contract import DenyExchangeClassification

GITHUB_REQUEST_URL_ENV: Final = "ACTIONS_ID_TOKEN_REQUEST_URL"
GITHUB_CREDENTIAL_ENV_NAME: Final = "ACTIONS_ID_TOKEN_REQUEST_TOKEN"
STS_URL: Final = "https://sts.googleapis.com/v1/token"
GRANT_TYPE: Final = "urn:ietf:params:oauth:grant-type:token-exchange"
REQUESTED_CREDENTIAL_TYPE: Final = "urn:ietf:params:oauth:token-type:access_token"
SUBJECT_CREDENTIAL_TYPE: Final = "urn:ietf:params:oauth:token-type:jwt"
CLOUD_PLATFORM_SCOPE: Final = "https://www.googleapis.com/auth/cloud-platform"
HTTP_OK: Final = 200
EXCHANGE_TIMEOUT: Final = httpx2.Timeout(
    connect=5.0,
    read=15.0,
    write=15.0,
    pool=15.0,
)


class GitHubOidcToken(BaseModel):
    """GitHub OIDC response parsed without exposing its subject token."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    value: str = Field(min_length=1)


def _wire_failure(
    provider_snapshot: str,
    provider_resource: str,
    code: str,
) -> DenyExchangeClassification:
    return classify_deny_exchange(
        provider_snapshot,
        provider_resource,
        httpx2.ConnectError(code),
    )


def probe_deny_exchange(
    provider_snapshot: str,
    provider_resource: str,
    transport: httpx2.BaseTransport | None = None,
) -> DenyExchangeClassification:
    """Verify provider state, fetch GitHub OIDC, and classify direct STS exchange."""
    provider_preflight = verify_deny_provider(provider_snapshot, provider_resource)
    if not provider_preflight.provider_verified:
        return provider_preflight
    request_url = os.environ.get(GITHUB_REQUEST_URL_ENV)
    request_token = os.environ.get(GITHUB_CREDENTIAL_ENV_NAME)
    if not request_url or not request_token:
        return _wire_failure(
            provider_snapshot,
            provider_resource,
            "github-oidc-authority-missing",
        )
    audience = f"//iam.googleapis.com/{provider_resource}"
    separator = "&" if "?" in request_url else "?"
    oidc_url = f"{request_url}{separator}{urlencode({'audience': audience})}"
    active_transport = transport or httpx2.HTTPTransport(
        http2=True,
        retries=0,
        limits=LIMITS,
        socket_options=SOCKET_OPTIONS,
    )
    try:
        with httpx2.Client(
            transport=active_transport,
            timeout=EXCHANGE_TIMEOUT,
            follow_redirects=True,
        ) as client:
            oidc_response = client.get(
                oidc_url,
                headers={"Authorization": f"Bearer {request_token}"},
            )
            if oidc_response.status_code != HTTP_OK:
                return _wire_failure(
                    provider_snapshot,
                    provider_resource,
                    f"github-oidc-http-{oidc_response.status_code}",
                )
            try:
                oidc = GitHubOidcToken.model_validate_json(oidc_response.content)
            except ValidationError:
                return _wire_failure(
                    provider_snapshot,
                    provider_resource,
                    "github-oidc-response-invalid",
                )
            sts_response = client.post(
                STS_URL,
                data={
                    "audience": audience,
                    "grant_type": GRANT_TYPE,
                    "requested_token_type": REQUESTED_CREDENTIAL_TYPE,
                    "scope": CLOUD_PLATFORM_SCOPE,
                    "subject_token": oidc.value,
                    "subject_token_type": SUBJECT_CREDENTIAL_TYPE,
                },
            )
    except httpx2.HTTPError as error:
        return classify_deny_exchange(
            provider_snapshot,
            provider_resource,
            error,
        )
    return classify_deny_exchange(
        provider_snapshot,
        provider_resource,
        sts_response,
    )
