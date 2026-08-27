"""Typed artifact models and deterministic fixtures for the Task5 CLI probe."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum, unique
from pathlib import Path
from typing import Final, assert_never, override

import anyio
from pydantic import JsonValue, TypeAdapter
from telco_twin.approval.authority import RootApprovalAuthority, SessionIssue
from telco_twin.counterfactual.comparison import (
    CounterfactualComparison,
)
from telco_twin.counterfactual.runner import CounterfactualRun
from telco_twin.data.synthetic import generate_manifest
from telco_twin.domain._contract import Sha256Hex, utc_datetime
from telco_twin.domain.approval import (
    ApprovalProof,
    ApprovalValidationContext,
    ContractViolationError,
    SessionKeyCertificate,
    validate_approval_chain,
)
from telco_twin.domain.canonical import canonical_json_bytes
from telco_twin.domain.event import Event
from telco_twin.domain.intervention import (
    BlastRadius,
    PatchChange,
    PatchOperation,
    TargetKind,
    TypedPatch,
)
from telco_twin.safety.local_policy import (
    LocalPolicyInput,
)
from telco_twin.simulator.frozen_event import FrozenEvent
from telco_twin.simulator.metrics import QualityPolicy
from telco_twin.simulator.network_model import load_scenario_manifests
from telco_twin.state.demo_token import DemoTokenKey
from telco_twin.state.memory_store import DemoSessionStore
from telco_twin.state.store_models import (
    AppendEventRequest,
    EventAppendAccepted,
    EventAppendDenied,
)

NOW: Final = datetime(2026, 8, 27, 0, 0, 0, tzinfo=UTC)
DEMO_KEY: Final = DemoTokenKey(b"task5-probe-demo-key-material-32b")
JSON_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)
SCENARIO_FIXTURES: Final = (
    Path(__file__).resolve().parents[1] / "backend/fixtures/scenarios"
)


@unique
class ProbeInvariantCode(StrEnum):
    """Stable internal probe failures that prevent a passing artifact."""

    COUNTERFACTUAL = "counterfactual-result-missing"
    SESSION_CREATE = "session-create-failed"
    EVENT_APPEND = "event-append-failed"
    SESSION_ACCESS = "session-access-failed"
    UNSAFE_REJECTION = "unsafe-rejection-missing"
    NEGATIVE_SESSION = "negative-session-result-missing"
    PROOF_RECORD = "approval-proof-record-missing"


@dataclass(frozen=True, slots=True)
class ProbeInvariantError(Exception):
    """The real probe failed to produce a required binary observable."""

    code: ProbeInvariantCode

    @override
    def __str__(self) -> str:
        return self.code.value


@dataclass(frozen=True, slots=True)
class ProbeUsageError(Exception):
    """The CLI did not receive its one required output path."""

    @override
    def __str__(self) -> str:
        return "usage: task5_safety_probe.py --out PATH"


@dataclass(frozen=True, slots=True)
class ApprovalNegativeCodes:
    """Stable expired and cross-session approval failures."""

    expired: str
    cross_session: str


def require_proof_hash(value: Sha256Hex | None) -> Sha256Hex:
    """Reject a missing proof hash instead of masking it with zeroes."""
    if value is None:
        raise ProbeInvariantError(ProbeInvariantCode.PROOF_RECORD)
    return value


def probe_approval_negatives(
    proof: ApprovalProof,
    context: ApprovalValidationContext,
    authority: RootApprovalAuthority,
) -> ApprovalNegativeCodes:
    """Run real expired and cross-session approval-chain negatives."""
    expired = "missing"
    expired_now = utc_datetime(proof.expires_at) + timedelta(seconds=1)
    try:
        validate_approval_chain(proof, replace(context, now=expired_now))
    except ContractViolationError as error:
        expired = error.code.value
    other = authority.issue_session(
        SessionIssue(session_id="session-probe-other", issued_at=proof.approved_at)
    )
    cross_session = _cross_session_code(proof, context, other.certificate)
    return ApprovalNegativeCodes(expired=expired, cross_session=cross_session)


def _cross_session_code(
    proof: ApprovalProof,
    context: ApprovalValidationContext,
    certificate: SessionKeyCertificate,
) -> str:
    code = "missing"
    try:
        validate_approval_chain(proof, replace(context, certificate=certificate))
    except ContractViolationError as error:
        code = error.code.value
    return code


def probe_patch() -> TypedPatch:
    """Return one baseline-bound allowed remediation patch."""
    manifest = generate_manifest(91)
    return TypedPatch(
        patch_id="patch-probe-0001",
        scenario_id=manifest.scenario.scenario_id,
        base_topology_hash=manifest.topology_hash,
        changes=(
            PatchChange(
                target_id="cell-0001",
                target_kind=TargetKind.CELL,
                operation=PatchOperation.ADJUST_RADIO_CAPACITY,
                parameters={"capacity_ues": 250},
            ),
        ),
        blast_radius=BlastRadius(max_cells=1, max_ue_cohorts=1, max_slices=1),
        proposed_at="2026-08-27T00:00:00Z",
        schema_version="1.0",
    )


def probe_policy_input(
    run: CounterfactualRun,
    comparison: CounterfactualComparison,
) -> LocalPolicyInput:
    """Bind one clean comparison to its actual deterministic run."""
    source = load_scenario_manifests(SCENARIO_FIXTURES)[0].observation
    observation = source.model_copy(
        update={
            "scenario_id": run.baseline_manifest.scenario.scenario_id,
            "topology_id": run.baseline_manifest.topology.topology_id,
        }
    )
    return LocalPolicyInput(
        observation=observation,
        quality_policy=QualityPolicy(),
        run=run,
        comparison=comparison,
    )


def probe_event(index: int, event_type: str, value: str) -> Event:
    """Return one deterministic append-only evidence event."""
    return Event(
        event_id=f"event-probe-{index:04d}",
        scenario_id="scenario-000000000005b",
        timestamp="2026-08-27T00:00:00Z",
        priority=0,
        sequence_id=index,
        event_type=event_type,
        payload={"evidence_ref": value},
        schema_version="1.0",
    )


async def probe_idempotency_race(
    store: DemoSessionStore,
    token: str,
    simulation_hash: Sha256Hex,
) -> tuple[EventAppendAccepted, ...]:
    """Run the bounded twelve-request same-key probe race."""
    results: list[EventAppendAccepted] = []

    async def append() -> None:
        result = await store.append_event(
            AppendEventRequest(
                token=token,
                idempotency_key="idem-probe-race",
                event=probe_event(99, "concurrency-recorded", simulation_hash),
            )
        )
        match result:
            case EventAppendAccepted():
                results.append(result)
            case EventAppendDenied():
                pass
            case _:
                assert_never(result)

    with anyio.fail_after(5):
        async with anyio.create_task_group() as group:
            for _ in range(12):
                _ = group.start_soon(append)
    return tuple(results)


def probe_snapshot_hash(events: tuple[FrozenEvent, ...]) -> str:
    """Hash the detached downloadable evidence snapshot independently."""
    value = JSON_ADAPTER.validate_python(
        {"events": [event.model_dump() for event in events]}
    )
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()
