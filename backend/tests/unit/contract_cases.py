"""Invalid and signed fixture cases for strict contract tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

from telco_twin.domain.approval import (
    ApprovalProof,
    ApprovalRequest,
    ApprovalValidationContext,
    Environment,
    RootDescriptor,
    SessionKeyCertificate,
)
from telco_twin.domain.event import Event
from telco_twin.domain.intervention import TypedPatch
from telco_twin.domain.scenario import Scenario
from telco_twin.domain.telemetry import Telemetry

from .contract_payloads import JsonObject, patch_payload

if TYPE_CHECKING:
    from pydantic import BaseModel

REPO_ROOT: Final = Path(__file__).resolve().parents[3]
APPROVAL_FIXTURES: Final = REPO_ROOT / "backend/tests/fixtures/approval"
SCHEMA_NAMES: Final = (
    "topology",
    "telemetry",
    "scenario",
    "event",
    "typed-patch",
    "simulation-result",
    "approval-request",
    "session-key-certificate",
    "approval-proof",
    "evidence-card",
    "service-build-info",
    "ui-build-info",
)


@dataclass(frozen=True, slots=True)
class InvalidContractCase:
    """One malformed boundary object and its expected stable error type."""

    model: type[BaseModel]
    payload: JsonObject
    error_code: str


@dataclass(frozen=True, slots=True)
class ApprovalBundle:
    """Golden root, session, request, and proof fixtures."""

    root: RootDescriptor
    certificate: SessionKeyCertificate
    request: ApprovalRequest
    proof: ApprovalProof


def approval_context() -> ApprovalValidationContext:
    """Return the fixed trust and time context for the golden approval chain."""
    bundle = load_approval_bundle()
    return ApprovalValidationContext(
        root=bundle.root,
        certificate=bundle.certificate,
        request=bundle.request,
        environment=Environment.TEST,
        trusted_root_hashes=frozenset({bundle.root.descriptor_hash}),
        consumed_nonces=frozenset(),
        now=datetime(2026, 8, 27, 0, 0, 30, tzinfo=UTC),
    )


def invalid_domain_cases() -> tuple[InvalidContractCase, ...]:
    """Return malformed boundaries for the required safety failures."""
    scenario_without_seed: JsonObject = {
        "scenario_id": "scenario-0001",
        "topology_id": "topology-0001",
        "fault_family": "radio-congestion",
        "starts_at": "2026-08-27T00:00:00Z",
        "duration_seconds": 60,
        "target_ids": ["cell-0001"],
        "parameters": {},
        "schema_version": "1.0",
    }
    patch = patch_payload()
    patch["blast_radius"] = {"max_cells": 5, "max_ue_cohorts": 2, "max_slices": 1}
    scenario_with_pii: JsonObject = {
        **scenario_without_seed,
        "seed": 7,
        "extensions": {
            "schema_version": "1.0",
            "values": {"msisdn": "synthetic"},
        },
    }
    return (
        InvalidContractCase(Scenario, scenario_without_seed, "missing"),
        InvalidContractCase(Scenario, scenario_with_pii, "pii_shaped_key"),
        InvalidContractCase(TypedPatch, patch, "less_than_equal"),
        InvalidContractCase(
            Event,
            {
                "event_id": "event-0001",
                "scenario_id": "scenario-0001",
                "timestamp": "2026-08-27T00:00:00Z",
                "priority": 0,
                "sequence_id": 0,
                "event_type": "metric-sampled",
                "payload": {"sample_count": 2**53},
                "schema_version": "1.0",
            },
            "less_than_equal",
        ),
        InvalidContractCase(
            Event,
            {
                "event_id": "event-0001",
                "scenario_id": "scenario-0001",
                "timestamp": "2026-08-27T00:00:00.1Z",
                "priority": 0,
                "sequence_id": 0,
                "event_type": "metric-sampled",
                "payload": {},
                "schema_version": "1.0",
            },
            "utc_rfc3339_seconds",
        ),
        InvalidContractCase(
            Telemetry,
            {
                "telemetry_id": "telemetry-0001",
                "topology_id": "topology-0001",
                "samples": [
                    {
                        "metric_name": "msisdn",
                        "target_id": "cell-0001",
                        "value": 1.0,
                        "unit": "count",
                        "observed_at": "2026-08-27T00:00:00Z",
                        "quality": "fresh",
                    }
                ],
                "schema_version": "1.0",
            },
            "pii_shaped_key",
        ),
        InvalidContractCase(
            Event,
            {
                "event_id": "event-0001",
                "scenario_id": "scenario-0001",
                "timestamp": "2026-08-27T00:00:00Z",
                "priority": 0,
                "sequence_id": 0,
                "event_type": "metric-sampled",
                "payload": {"command": "echo unsafe"},
                "schema_version": "1.0",
            },
            "authority_shaped_key",
        ),
    )


def load_approval_bundle() -> ApprovalBundle:
    """Parse every committed golden approval fixture through its boundary."""
    return ApprovalBundle(
        root=RootDescriptor.model_validate_json(
            (APPROVAL_FIXTURES / "test-root-descriptor.json").read_bytes()
        ),
        certificate=SessionKeyCertificate.model_validate_json(
            (APPROVAL_FIXTURES / "test-session-certificate.json").read_bytes()
        ),
        request=ApprovalRequest.model_validate_json(
            (APPROVAL_FIXTURES / "test-approval-request.json").read_bytes()
        ),
        proof=ApprovalProof.model_validate_json(
            (APPROVAL_FIXTURES / "test-approval-proof.json").read_bytes()
        ),
    )
