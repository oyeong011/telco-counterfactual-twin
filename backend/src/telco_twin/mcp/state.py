"""Evidence-state implementation behind the twin MCP tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, assert_never

if TYPE_CHECKING:
    from collections.abc import Mapping

    from telco_twin.mcp.contracts import JsonValue

from telco_twin.counterfactual.comparison import compare_counterfactual, hash_comparison
from telco_twin.counterfactual.runner import (
    CounterfactualRejected,
    CounterfactualRun,
    run_counterfactual,
)
from telco_twin.data.synthetic import SimulationManifest, generate_manifest
from telco_twin.domain.intervention import (
    BlastRadius,
    PatchChange,
    PatchOperation,
    TargetKind,
    TypedPatch,
)
from telco_twin.mcp.contracts import tool_manifest
from telco_twin.mcp.state_errors import McpToolError
from telco_twin.mcp.state_records import (
    ApprovalRequestRecord,
    DiagnosisRecord,
    SimulationDraft,
    ensure_room,
)
from telco_twin.mcp.state_types import JsonObject
from telco_twin.mcp.state_validation import (
    required_id,
    stable_id,
    tool_error,
    validate_arguments,
)

DEFAULT_SEED: Final = 53
DEFAULT_RECORD_CAP: Final = 256
__all__ = [
    "ApprovalRequestRecord",
    "DiagnosisRecord",
    "EvidenceMcpService",
    "JsonObject",
    "McpToolError",
]


@dataclass(slots=True)
class EvidenceMcpService:
    """In-memory evidence map with no network-facing authority side effect."""

    _scenarios: dict[str, SimulationManifest] = field(default_factory=dict)
    _patches: dict[str, TypedPatch] = field(default_factory=dict)
    _runs: dict[str, SimulationDraft] = field(default_factory=dict)
    _comparisons: dict[str, str] = field(default_factory=dict)
    _diagnoses: dict[str, DiagnosisRecord] = field(default_factory=dict)
    _approval_requests: dict[str, ApprovalRequestRecord] = field(default_factory=dict)
    review_draft_only: bool = True
    max_records: int = DEFAULT_RECORD_CAP

    def __post_init__(self) -> None:
        """Seed one deterministic scenario when callers do not provide fixtures."""
        manifest = generate_manifest(DEFAULT_SEED)
        self._scenarios[manifest.scenario.scenario_id] = manifest

    async def call_tool(self, name: str, arguments: Mapping[str, JsonValue]) -> JsonObject:
        """Route one typed MCP tool call into the evidence-state map."""
        validate_arguments(name, arguments)
        match name:
            case "list_scenarios":
                result = self._list_scenarios()
            case "get_scenario":
                result = self._get_scenario(required_id(arguments, "scenario_id"))
            case "diagnose_scenario":
                result = self._diagnose(required_id(arguments, "scenario_id"))
            case "propose_patch":
                result = self._propose(
                    required_id(arguments, "scenario_id"),
                    required_id(arguments, "target_id"),
                )
            case "simulate_patch":
                result = self._simulate(
                    required_id(arguments, "scenario_id"),
                    required_id(arguments, "patch_id"),
                )
            case "compare_runs":
                result = self._compare(required_id(arguments, "simulation_id"))
            case "request_approval":
                result = self._request_approval(
                    required_id(arguments, "comparison_id"),
                    required_id(arguments, "simulation_id"),
                )
            case _:
                code = "unknown_tool"
                raise tool_error(code, "tool is not exposed")
        return result

    def _list_scenarios(self) -> JsonObject:
        scenarios = [
            {
                "scenario_id": manifest.scenario.scenario_id,
                "seed": manifest.seed,
                "fault_family": manifest.scenario.fault_family.value,
            }
            for manifest in self._scenarios.values()
        ]
        return {"tools": tool_manifest()["tools"], "scenarios": scenarios}

    def _get_scenario(self, scenario_id: str) -> JsonObject:
        manifest = _scenario(self._scenarios, scenario_id)
        return {
            "scenario_id": scenario_id,
            "topology_hash": manifest.topology_hash,
            "manifest_hash": manifest.manifest_hash,
            "target_id": manifest.scenario.target_ids[0],
        }

    def _diagnose(self, scenario_id: str) -> JsonObject:
        manifest = _scenario(self._scenarios, scenario_id)
        diagnosis_id = stable_id("diagnosis", scenario_id, manifest.manifest_hash)
        if diagnosis_id not in self._diagnoses:
            ensure_room(self._diagnoses, self.max_records)
        self._diagnoses[diagnosis_id] = DiagnosisRecord(
            diagnosis_id=diagnosis_id,
            scenario_id=scenario_id,
            target_id=manifest.scenario.target_ids[0],
            manifest_hash=manifest.manifest_hash,
        )
        return {
            "status": "recorded",
            "effect": "diagnosis_evidence_recorded",
            "diagnosis_id": diagnosis_id,
            "scenario_id": scenario_id,
            "target_id": manifest.scenario.target_ids[0],
        }

    def _propose(self, scenario_id: str, target_id: str) -> JsonObject:
        manifest = _scenario(self._scenarios, scenario_id)
        if target_id not in manifest.scenario.target_ids:
            code = "unknown_target"
            raise tool_error(code, "target does not belong to the scenario")
        patch_id = stable_id("patch", scenario_id, target_id)[:24]
        if patch_id not in self._patches:
            ensure_room(self._patches, self.max_records)
        patch = TypedPatch(
            patch_id=patch_id,
            scenario_id=scenario_id,
            base_topology_hash=manifest.topology_hash,
            changes=(
                PatchChange(
                    target_id=target_id,
                    target_kind=TargetKind.CELL,
                    operation=PatchOperation.ADJUST_RADIO_CAPACITY,
                    parameters={"capacity_ues": 240},
                ),
            ),
            blast_radius=BlastRadius(max_cells=1, max_ue_cohorts=1, max_slices=1),
            proposed_at=manifest.scenario.starts_at,
            schema_version="1.0",
        )
        self._patches[patch.patch_id] = patch
        return {"status": "draft", "effect": "patch_recorded", "patch_id": patch.patch_id}

    def _simulate(self, scenario_id: str, patch_id: str) -> JsonObject:
        manifest = _scenario(self._scenarios, scenario_id)
        patch = _patch(self._patches, patch_id)
        outcome = run_counterfactual(manifest, patch)
        match outcome:
            case CounterfactualRejected(assessment=assessment):
                raise tool_error(assessment.code.value, "candidate patch was rejected")
            case CounterfactualRun():
                simulation_id = stable_id("simulation", scenario_id, patch_id)[:32]
                if simulation_id not in self._runs:
                    ensure_room(self._runs, self.max_records)
                self._runs[simulation_id] = SimulationDraft(
                    scenario_id=scenario_id,
                    patch_id=patch_id,
                    run=outcome,
                    simulation_id=simulation_id,
                )
                return {
                    "status": "recorded",
                    "effect": "simulation_evidence_recorded",
                    "simulation_id": simulation_id,
                    "patch_hash": outcome.patch_hash,
                }
            case _:  # pragma: no cover - exhaustive union
                assert_never(outcome)

    def _compare(self, simulation_id: str) -> JsonObject:
        draft = _run(self._runs, simulation_id)
        comparison = compare_counterfactual(draft.run, simulation_id)
        comparison_id = stable_id("comparison", simulation_id, hash_comparison(comparison))[:32]
        if comparison_id not in self._comparisons:
            ensure_room(self._comparisons, self.max_records)
        self._comparisons[comparison_id] = simulation_id
        return {
            "status": "recorded",
            "effect": "comparison_evidence_recorded",
            "comparison_id": comparison_id,
            "simulation_id": simulation_id,
            "approval_eligible": comparison.result.approval_eligible,
        }

    def _request_approval(self, comparison_id: str, simulation_id: str) -> JsonObject:
        if simulation_id not in self._runs:
            code = "missing_simulation"
            raise tool_error(code, "simulation must be recorded first")
        if comparison_id not in self._comparisons:
            code = "missing_comparison"
            raise tool_error(code, "comparison must be recorded first")
        if self._comparisons[comparison_id] != simulation_id:
            code = "missing_simulation"
            raise tool_error(code, "simulation must be recorded first")
        request_id = stable_id("approval-request", comparison_id, simulation_id)[:40]
        if request_id not in self._approval_requests:
            ensure_room(self._approval_requests, self.max_records)
        self._approval_requests[request_id] = ApprovalRequestRecord(
            approval_request_id=request_id,
            comparison_id=comparison_id,
            simulation_id=simulation_id,
            network_change_permitted=False,
        )
        return {
            "status": "draft",
            "effect": "approval_request_recorded",
            "approval_request_id": request_id,
            "simulation_id": simulation_id,
            "network_change_permitted": False,
        }

    def diagnosis_records(self) -> tuple[DiagnosisRecord, ...]:
        """Return append-only diagnosis records for tests and local QA evidence."""
        return tuple(self._diagnoses.values())

    def approval_request_records(self) -> tuple[ApprovalRequestRecord, ...]:
        """Return append-only approval draft records for tests and local QA evidence."""
        return tuple(self._approval_requests.values())


def _scenario(items: dict[str, SimulationManifest], scenario_id: str) -> SimulationManifest:
    manifest = items.get(scenario_id)
    if manifest is None:
        code = "unknown_scenario"
        raise tool_error(code, "scenario is not available")
    return manifest


def _patch(items: dict[str, TypedPatch], patch_id: str) -> TypedPatch:
    patch = items.get(patch_id)
    if patch is None:
        code = "unknown_patch"
        raise tool_error(code, "patch must be proposed first")
    return patch


def _run(items: dict[str, SimulationDraft], simulation_id: str) -> SimulationDraft:
    draft = items.get(simulation_id)
    if draft is None:
        code = "missing_simulation"
        raise tool_error(code, "simulation must be recorded first")
    return draft
