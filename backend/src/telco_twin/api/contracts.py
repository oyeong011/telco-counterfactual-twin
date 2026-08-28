"""Closed request and response models for the public FastAPI surface."""
# ruff: noqa: TC001 - Pydantic resolves these field types at runtime.

from __future__ import annotations

from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from telco_twin.approval.state_machine import ApprovalEvidenceState
from telco_twin.counterfactual.comparison import CounterfactualComparison
from telco_twin.domain._contract import ContractId, Seed, Sha256Hex, UtcTimestamp
from telco_twin.domain.approval import ApprovalProof, ApprovalRequest, SessionKeyCertificate
from telco_twin.domain.event import Event
from telco_twin.domain.evidence import EvidenceCard
from telco_twin.domain.intervention import TypedPatch
from telco_twin.domain.scenario import FaultFamily, Scenario
from telco_twin.domain.simulation_result import SimulationResult
from telco_twin.safety.local_policy import PolicyEvaluation
from telco_twin.simulator.faults import DiagnosisStatus


class ApiContract(BaseModel):
    """Frozen closed model for values crossing the HTTP trust boundary."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        frozen=True,
    )


class EmptyRequest(ApiContract):
    """Explicit empty JSON body for idempotent command routes."""


class DemoSessionRequest(ApiContract):
    """Synthetic-only acknowledgement required by the bootstrap."""

    synthetic_only: Literal[True]


class DemoSessionResponse(ApiContract):
    """Opaque live-session bearer plus only public approval-key material."""

    session_id: ContractId
    demo_token: str
    session_certificate: SessionKeyCertificate
    expires_at: UtcTimestamp
    startup_epoch: ContractId
    durability: Literal["process-memory"]
    synthetic_only: Literal[True]


class ScenarioCreateRequest(ApiContract):
    """Bounded generator input for one synthetic scenario."""

    fault_family: FaultFamily
    seed: Seed


class ScenarioResponse(ApiContract):
    """Session-scoped scenario plus its exact baseline identity."""

    scenario: Scenario
    topology_hash: Sha256Hex
    scenario_hash: Sha256Hex
    run_id: ContractId


class ScenarioListResponse(ApiContract):
    """Stable creation-order scenario collection."""

    items: tuple[ScenarioResponse, ...]


class DiagnosisResponse(ApiContract):
    """Closed six-family diagnosis evidence."""

    scenario_id: ContractId
    run_id: ContractId
    status: DiagnosisStatus
    primary_fault: FaultFamily | None
    secondary_evidence: tuple[FaultFamily, ...]


class PatchResponse(ApiContract):
    """Accepted simulation-only patch identity."""

    patch: TypedPatch
    patch_hash: Sha256Hex
    run_id: ContractId


class SimulationResponse(ApiContract):
    """Completed deterministic fork identity without mutable implementation state."""

    simulation_id: ContractId
    scenario_id: ContractId
    patch_id: ContractId
    run_id: ContractId
    status: Literal["completed"]
    trace_hash: Sha256Hex


class SimulationReadResponse(ApiContract):
    """Public projection of a completed simulation."""

    simulation: SimulationResponse
    result: SimulationResult | None


class ComparisonResponse(ApiContract):
    """Baseline/candidate comparison and supporting hashes."""

    comparison_id: ContractId
    run_id: ContractId
    comparison: CounterfactualComparison


class ApprovalRequestResponse(ApiContract):
    """Pending evidence request plus recomputed local-policy result."""

    approval_request: ApprovalRequest
    policy: PolicyEvaluation
    run_id: ContractId
    evidence_id: ContractId


class ApprovalReadResponse(ApiContract):
    """Current append-only approval evidence state."""

    approval_request: ApprovalRequest
    state: ApprovalEvidenceState
    proof_hash: Sha256Hex | None


class ApprovalDecisionResponse(ApiContract):
    """Terminal signed evidence that explicitly grants no runtime authority."""

    state: ApprovalEvidenceState
    approval_proof: ApprovalProof
    effect: Literal["evidence-only"]


class BenchmarkRequest(ApiContract):
    """Bounded real-simulator determinism probe input."""

    seed: Seed
    iterations: Annotated[int, Field(ge=2, le=25)]


class BenchmarkResponse(ApiContract):
    """Observed trace-hash agreement from actual simulator calls."""

    seed: Seed
    iterations: int
    unique_trace_hashes: int
    deterministic: bool
    trace_hash: Sha256Hex


class HealthResponse(ApiContract):
    """Process-only liveness response."""

    status: Literal["live"]


class ReadyResponse(ApiContract):
    """Safe dependency readiness response."""

    status: Literal["ready", "degraded"]
    checks: dict[str, bool]


class EvidenceResponse(ApiContract):
    """Downloadable live evidence scoped to one run stream."""

    run_id: ContractId
    evidence_card: EvidenceCard
    events: tuple[Event, ...]
    approval_proof: ApprovalProof | None
