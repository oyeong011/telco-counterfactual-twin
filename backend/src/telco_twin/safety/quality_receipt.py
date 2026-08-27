"""Sealed observation-quality provenance with trusted-time revalidation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import TYPE_CHECKING, final, override

from telco_twin.domain._contract import Sha256Hex, StrictContract, UtcTimestamp
from telco_twin.domain.canonical import canonical_model_bytes
from telco_twin.simulator.metrics import (
    QualityAssessment,
    QualityContext,
    QualityPolicy,
    assess_observation_quality,
)
from telco_twin.state.trusted_clock import trusted_timestamp

if TYPE_CHECKING:
    from telco_twin.simulator.network_model import NetworkObservation
    from telco_twin.state.trusted_clock import TrustedClock


class QualityReceiptEvidence(StrictContract):
    """Serializable hashes and assessment issued from actual observation input."""

    observation_hash: Sha256Hex
    context_hash: Sha256Hex
    assessed_at: UtcTimestamp
    assessment: QualityAssessment


@dataclass(frozen=True, slots=True)
class QualityReceiptIssuer:
    """Module identity preventing ordinary receipt construction."""


QUALITY_RECEIPT_ISSUER = QualityReceiptIssuer()


@dataclass(frozen=True, slots=True)
class QualityReceiptPayload:
    """Immutable source objects and their issued evidence projection."""

    observation: NetworkObservation
    policy: QualityPolicy
    evidence: QualityReceiptEvidence


@dataclass(frozen=True, slots=True)
class QualityReceiptCreationError(Exception):
    """A caller attempted to construct quality provenance directly."""

    @override
    def __str__(self) -> str:
        return "quality-receipt-construction-forbidden"


@final
class QualityReceipt:
    """Internal capability retaining observation, settings, and issued evidence."""

    __slots__ = ("_payload",)

    def __init__(
        self,
        issuer: QualityReceiptIssuer,
        payload: QualityReceiptPayload,
    ) -> None:
        """Accept construction only from this module's assessor."""
        if issuer is not QUALITY_RECEIPT_ISSUER:
            raise QualityReceiptCreationError
        self._payload = payload

    @property
    def observation(self) -> NetworkObservation:
        """Return the immutable source observation."""
        return self._payload.observation

    @property
    def policy(self) -> QualityPolicy:
        """Return the immutable quality settings."""
        return self._payload.policy

    @property
    def evidence(self) -> QualityReceiptEvidence:
        """Return the detached serializable receipt projection."""
        return self._payload.evidence


@unique
class QualityReceiptErrorCode(StrEnum):
    """Stable quality-provenance revalidation failures."""

    EVIDENCE_CHANGED = "quality-evidence-changed"
    CURRENTLY_INELIGIBLE = "quality-currently-ineligible"


@dataclass(frozen=True, slots=True)
class QualityReceiptRejected:
    """Fail-closed quality receipt result."""

    code: QualityReceiptErrorCode


type QualityReceiptValidation = QualityReceiptEvidence | QualityReceiptRejected


def _hash(value: StrictContract) -> Sha256Hex:
    return hashlib.sha256(canonical_model_bytes(value)).hexdigest()


def _evidence(
    observation: NetworkObservation,
    policy: QualityPolicy,
    assessed_at: UtcTimestamp,
) -> QualityReceiptEvidence:
    context = QualityContext(assessed_at=assessed_at, policy=policy)
    return QualityReceiptEvidence(
        observation_hash=_hash(observation),
        context_hash=_hash(context),
        assessed_at=assessed_at,
        assessment=assess_observation_quality(observation, context),
    )


def issue_quality_receipt(
    observation: NetworkObservation,
    policy: QualityPolicy,
    clock: TrustedClock,
) -> QualityReceipt:
    """Assess actual observation evidence at one trusted instant and seal it."""
    evidence = _evidence(observation, policy, trusted_timestamp(clock))
    return QualityReceipt(
        QUALITY_RECEIPT_ISSUER,
        QualityReceiptPayload(
            observation=observation,
            policy=policy,
            evidence=evidence,
        ),
    )


def quality_receipt_hash(receipt: QualityReceipt) -> Sha256Hex:
    """Hash the complete serializable quality evidence."""
    return _hash(receipt.evidence)


def revalidate_quality_receipt(
    receipt: QualityReceipt,
    clock: TrustedClock,
) -> QualityReceiptValidation:
    """Verify issued evidence and reject eligibility lost as trusted time advances."""
    expected = _evidence(
        receipt.observation,
        receipt.policy,
        receipt.evidence.assessed_at,
    )
    if expected != receipt.evidence:
        return QualityReceiptRejected(QualityReceiptErrorCode.EVIDENCE_CHANGED)
    current = _evidence(receipt.observation, receipt.policy, trusted_timestamp(clock))
    if receipt.evidence.assessment.approval_eligible and not current.assessment.approval_eligible:
        return QualityReceiptRejected(QualityReceiptErrorCode.CURRENTLY_INELIGIBLE)
    return receipt.evidence
