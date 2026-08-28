"""Private in-memory resources retained only for one process epoch."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, final

import anyio

if TYPE_CHECKING:
    from telco_twin.approval.authority import SessionApprovalAuthority
    from telco_twin.approval.state_machine import ApprovalStateMachine
    from telco_twin.counterfactual.comparison import CounterfactualComparison
    from telco_twin.counterfactual.runner import CounterfactualRun
    from telco_twin.data.synthetic import SimulationManifest
    from telco_twin.domain._contract import ContractId, Sha256Hex
    from telco_twin.domain.approval import ApprovalProof, ApprovalRequest
    from telco_twin.domain.intervention import TypedPatch
    from telco_twin.safety.local_policy import PolicyDecision
    from telco_twin.simulator.frozen_event import FrozenEvent
    from telco_twin.simulator.network_model import NetworkObservation


@dataclass(frozen=True, slots=True)
class ScenarioResource:
    """Private manifest/observation pair for one public scenario."""

    manifest: SimulationManifest
    observation: NetworkObservation
    run_id: ContractId


@dataclass(frozen=True, slots=True)
class PatchResource:
    """Accepted patch and its canonical run binding."""

    patch: TypedPatch
    patch_hash: Sha256Hex
    run_id: ContractId


@dataclass(frozen=True, slots=True)
class SimulationResource:
    """Retained immutable counterfactual run."""

    simulation_id: ContractId
    run_id: ContractId
    patch_id: ContractId
    run: CounterfactualRun


@dataclass(frozen=True, slots=True)
class ComparisonResource:
    """Retained comparison and its simulation binding."""

    comparison_id: ContractId
    run_id: ContractId
    simulation_id: ContractId
    comparison: CounterfactualComparison


@dataclass(frozen=True, slots=True)
class ApprovalResource:
    """Pending or terminal approval evidence capability."""

    request: ApprovalRequest
    policy: PolicyDecision
    run_id: ContractId
    evidence_id: ContractId
    proof: ApprovalProof | None = None


@dataclass(frozen=True, slots=True)
class RunResource:
    """Linked identifiers for one governed lifecycle run."""

    run_id: ContractId
    scenario_id: ContractId
    patch_id: ContractId | None = None
    simulation_id: ContractId | None = None
    comparison_id: ContractId | None = None
    approval_request_id: ContractId | None = None


@dataclass(frozen=True, slots=True)
class ApiIdempotencyRecord:
    """Session-wide request identity and its original immutable event."""

    request_hash: Sha256Hex
    event: FrozenEvent


@final
class ApiSession:
    """Mutable session aggregate serialized by one AnyIO lock."""

    def __init__(
        self,
        session_id: ContractId,
        signer: SessionApprovalAuthority,
        approvals: ApprovalStateMachine,
    ) -> None:
        """Create an empty private session aggregate."""
        self.session_id = session_id
        self.signer = signer
        self.approvals = approvals
        self.lock = anyio.Lock()
        self.next_event_sequence = 0
        self.scenarios: dict[ContractId, ScenarioResource] = {}
        self.patches: dict[ContractId, PatchResource] = {}
        self.simulations: dict[ContractId, SimulationResource] = {}
        self.comparisons: dict[ContractId, ComparisonResource] = {}
        self.approval_requests: dict[ContractId, ApprovalResource] = {}
        self.runs: dict[ContractId, RunResource] = {}
        self.external_events: list[FrozenEvent] = []
        self.idempotency: dict[ContractId, ApiIdempotencyRecord] = {}
