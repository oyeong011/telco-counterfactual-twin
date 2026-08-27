"""Typed artifact models and deterministic fixtures for the Task5 CLI probe."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum, unique
from typing import ClassVar, Final, Literal, override

from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter
from telco_twin.counterfactual.comparison import (
    CounterfactualComparison,
    hash_comparison,
)
from telco_twin.counterfactual.runner import CounterfactualRun
from telco_twin.data.synthetic import generate_manifest
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
    LOCAL_POLICY_DEFINITION_HASH,
    LocalPolicyInput,
    PolicyBindings,
)
from telco_twin.simulator.frozen_event import FrozenEvent
from telco_twin.simulator.metrics import QualityAssessment
from telco_twin.state.demo_token import DemoTokenKey

NOW: Final = datetime(2026, 8, 27, 0, 0, 0, tzinfo=UTC)
DEMO_KEY: Final = DemoTokenKey(b"task5-probe-demo-key-material-32b")
JSON_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


@unique
class ProbeInvariantCode(StrEnum):
    """Stable internal probe failures that prevent a passing artifact."""

    COUNTERFACTUAL = "counterfactual-result-missing"
    SESSION_CREATE = "session-create-failed"
    EVENT_APPEND = "event-append-failed"
    SESSION_ACCESS = "session-access-failed"
    UNSAFE_REJECTION = "unsafe-rejection-missing"
    NEGATIVE_SESSION = "negative-session-result-missing"


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


class _ArtifactModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)


class PositiveEvidence(_ArtifactModel):
    baseline_hash_before: str
    baseline_hash_after: str
    candidate_hash: str
    comparison_hash: str
    policy_hash: str
    certificate_hash: str
    proof_hash: str
    evidence_snapshot_hash: str
    approval_state: Literal["approved"]
    offline_chain_verified: Literal[True]


class NegativeEvidence(_ArtifactModel):
    replay_code: str
    epoch_code: str
    malformed_code: str
    unsafe_patch_code: str
    stale_policy_code: str
    unsimulated_policy_code: str
    forged_proof_code: str
    dirty_baseline_code: str


class ConcurrencyEvidence(_ArtifactModel):
    requests: int
    original_appends: int
    replays: int
    event_count: int


class CleanupEvidence(_ArtifactModel):
    external_resources_created: Literal[False]
    in_memory_only: Literal[True]
    cancellation_required: Literal[False]


class ProbeArtifact(_ArtifactModel):
    schema_version: Literal["1.0"]
    result: Literal["pass"]
    positive: PositiveEvidence
    negative: NegativeEvidence
    concurrency: ConcurrencyEvidence
    cleanup: CleanupEvidence


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
    """Bind one clean comparison to the local policy definition."""
    comparison_digest = hash_comparison(comparison)
    return LocalPolicyInput(
        quality=QualityAssessment(flags=(), approval_eligible=True),
        comparison=comparison,
        bindings=PolicyBindings(
            expected_patch_hash=run.patch_hash,
            observed_patch_hash=run.patch_hash,
            expected_simulation_hash=comparison_digest,
            observed_simulation_hash=comparison_digest,
            expected_policy_definition_hash=LOCAL_POLICY_DEFINITION_HASH,
            observed_policy_definition_hash=LOCAL_POLICY_DEFINITION_HASH,
        ),
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


def probe_snapshot_hash(events: tuple[FrozenEvent, ...]) -> str:
    """Hash the detached downloadable evidence snapshot independently."""
    value = JSON_ADAPTER.validate_python(
        {"events": [event.model_dump() for event in events]}
    )
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()
