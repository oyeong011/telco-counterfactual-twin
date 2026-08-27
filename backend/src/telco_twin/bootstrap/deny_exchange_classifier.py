"""Typed, secret-safe classification of Google STS deny exchanges."""

from __future__ import annotations

import hashlib
from typing import assert_never

import httpx2
from pydantic import ValidationError

from telco_twin.bootstrap.deny_exchange_contract import (
    CONDITION_REJECTION_DESCRIPTION,
    CONDITION_REJECTION_ERRORS,
    EXPECTED_CONDITION,
    EXPECTED_ISSUER,
    EXPECTED_MAPPING_ITEMS,
    HTTP_BAD_REQUEST,
    HTTP_SUCCESS_MAX,
    HTTP_SUCCESS_MIN,
    ClassificationFacts,
    DenyExchangeClassification,
    DenyProviderSnapshot,
    StsErrorResponse,
    StsSuccessResponse,
)
from telco_twin.bootstrap.preflight_contract import receipt_for


def _report(facts: ClassificationFacts, provider_evidence: str) -> DenyExchangeClassification:
    return DenyExchangeClassification(
        status=facts.status,
        provider_verified=facts.provider_verified,
        http_status=facts.http_status,
        sts_error=facts.sts_error,
        provider_evidence=provider_evidence,
        exchange_evidence=receipt_for(
            "deny-sts",
            facts.status,
            str(facts.http_status),
            str(facts.sts_error),
            facts.seed,
        ),
    )


def _provider_evidence(
    provider_snapshot: str,
    provider_resource: str,
) -> tuple[bool, str]:
    snapshot_hash = hashlib.sha256(provider_snapshot.encode()).hexdigest()
    try:
        snapshot = DenyProviderSnapshot.model_validate_json(provider_snapshot)
    except ValidationError:
        return False, receipt_for("deny-provider-invalid", snapshot_hash)
    mapping_items = tuple(sorted(snapshot.mapping.items()))
    verified = (
        snapshot.name == provider_resource
        and snapshot.issuer == EXPECTED_ISSUER
        and mapping_items == EXPECTED_MAPPING_ITEMS
        and snapshot.condition == EXPECTED_CONDITION
    )
    return (
        verified,
        receipt_for(
            "deny-provider",
            snapshot.name,
            snapshot.issuer,
            repr(mapping_items),
            snapshot.condition,
        ),
    )


def _unproven(
    provider_evidence: str,
    *,
    provider_verified: bool,
    http_status: int | None = None,
    sts_error: str | None = None,
    seed: str,
) -> DenyExchangeClassification:
    return _report(
        ClassificationFacts(
            status="deny-exchange-rejection-unproven",
            provider_verified=provider_verified,
            http_status=http_status,
            sts_error=sts_error,
            seed=seed,
        ),
        provider_evidence,
    )


def verify_deny_provider(
    provider_snapshot: str,
    provider_resource: str,
) -> DenyExchangeClassification:
    """Project exact provider verification into a redacted pre-exchange result."""
    provider_verified, provider_evidence = _provider_evidence(
        provider_snapshot,
        provider_resource,
    )
    return _unproven(
        provider_evidence,
        provider_verified=provider_verified,
        seed="provider-verified" if provider_verified else "provider-unverified",
    )


def _classify_verified_exchange(
    observation: httpx2.Response | httpx2.HTTPError,
    provider_evidence: str,
) -> DenyExchangeClassification:
    match observation:
        case httpx2.HTTPError() as transport_error:
            return _unproven(
                provider_evidence,
                provider_verified=True,
                seed=type(transport_error).__name__,
            )
        case httpx2.Response() as response:
            pass
        case _:
            assert_never(observation)
    status_code = response.status_code
    if HTTP_SUCCESS_MIN <= status_code < HTTP_SUCCESS_MAX:
        try:
            _ = StsSuccessResponse.model_validate_json(response.content)
        except ValidationError:
            return _unproven(
                provider_evidence,
                provider_verified=True,
                http_status=status_code,
                seed="malformed-success",
            )
        return _report(
            ClassificationFacts(
                status="deny-exchange-unexpected-success",
                provider_verified=True,
                http_status=status_code,
                sts_error=None,
                seed="access-token-present",
            ),
            provider_evidence,
        )
    try:
        sts_error_response = StsErrorResponse.model_validate_json(response.content)
    except ValidationError:
        return _unproven(
            provider_evidence,
            provider_verified=True,
            http_status=status_code,
            seed="malformed-error",
        )
    condition_rejected = (
        status_code == HTTP_BAD_REQUEST
        and sts_error_response.error in CONDITION_REJECTION_ERRORS
        and sts_error_response.error_description == CONDITION_REJECTION_DESCRIPTION
    )
    if not condition_rejected:
        return _unproven(
            provider_evidence,
            provider_verified=True,
            http_status=status_code,
            sts_error=sts_error_response.error,
            seed=sts_error_response.error_description,
        )
    return _report(
        ClassificationFacts(
            status="deny-rejected",
            provider_verified=True,
            http_status=status_code,
            sts_error=sts_error_response.error,
            seed=CONDITION_REJECTION_DESCRIPTION,
        ),
        provider_evidence,
    )


def classify_deny_exchange(
    provider_snapshot: str,
    provider_resource: str,
    observation: httpx2.Response | httpx2.HTTPError,
) -> DenyExchangeClassification:
    """Accept only the exact documented attribute-condition rejection tuple."""
    provider_verified, provider_evidence = _provider_evidence(
        provider_snapshot,
        provider_resource,
    )
    if not provider_verified:
        return _unproven(
            provider_evidence,
            provider_verified=False,
            seed="provider-unverified",
        )
    return _classify_verified_exchange(observation, provider_evidence)
