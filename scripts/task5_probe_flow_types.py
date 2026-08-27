"""Typed dependency bundles for split Task5 probe scenarios."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from telco_twin.approval.authority import RootApprovalAuthority
from telco_twin.approval.state_machine import ApprovalStateMachine
from telco_twin.data.synthetic import SimulationManifest
from telco_twin.domain.approval import ApprovalProof, ApprovalValidationContext
from telco_twin.domain.intervention import TypedPatch
from telco_twin.safety.local_policy import LocalPolicyInput
from telco_twin.state.memory_store import DemoSessionStore
from telco_twin.state.trusted_clock import FixedClock


@dataclass(frozen=True, slots=True)
class ApprovalNegativeInputs:
    """Configured trust and proof objects for approval negatives."""

    proof: ApprovalProof
    context: ApprovalValidationContext
    authority: RootApprovalAuthority
    machine: ApprovalStateMachine


@dataclass(frozen=True, slots=True)
class StoreNegativeInputs:
    """Authenticated live-store objects for token negatives."""

    store: DemoSessionStore
    token: str
    clock: FixedClock


@dataclass(frozen=True, slots=True)
class ScenarioNegativeInputs:
    """Simulation and quality inputs for unsafe/stale/dirty negatives."""

    manifest: SimulationManifest
    patch: TypedPatch
    policy_input: LocalPolicyInput
    stale_time: datetime


@dataclass(frozen=True, slots=True)
class ProbeNegativeInputs:
    """Three coherent negative-scenario dependency groups."""

    approval: ApprovalNegativeInputs
    store: StoreNegativeInputs
    scenario: ScenarioNegativeInputs
