"""Session-scoped scenario, diagnosis, and typed-patch lifecycle."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, assert_never, final

from telco_twin.api.contracts import (
    DiagnosisResponse,
    EmptyRequest,
    PatchResponse,
    ScenarioCreateRequest,
    ScenarioListResponse,
    ScenarioResponse,
)
from telco_twin.api.errors import ProblemError
from telco_twin.api.mutations import EvidenceAppend, append_mutation, stable_id
from telco_twin.api.runtime_models import PatchResource, RunResource, ScenarioResource
from telco_twin.counterfactual.patches import PatchAccepted, PatchRejected, assess_patch
from telco_twin.simulator.faults import diagnose_fault
from telco_twin.state.trusted_clock import trusted_timestamp

if TYPE_CHECKING:
    from telco_twin.api.runtime import ApiRuntime, AuthorizedSession
    from telco_twin.domain.intervention import TypedPatch


def scenario_response(resource: ScenarioResource) -> ScenarioResponse:
    """Project one private scenario resource into its public contract."""
    return ScenarioResponse(
        scenario=resource.manifest.scenario,
        topology_hash=resource.manifest.topology_hash,
        scenario_hash=resource.manifest.scenario_hash,
        run_id=resource.run_id,
    )


@final
class ScenarioLifecycle:
    """Own scenario creation, diagnosis, and patch admission."""

    def __init__(self, runtime: ApiRuntime) -> None:
        """Bind the lifecycle to one process runtime."""
        self._runtime = runtime

    async def create(
        self,
        authorized: AuthorizedSession,
        idempotency_key: str,
        request: ScenarioCreateRequest,
    ) -> tuple[ScenarioResponse, bool]:
        """Create or replay one deterministic session-scoped scenario."""
        session = authorized.session
        scenario_id = stable_id("scenario", session.session_id, idempotency_key)
        run_id = stable_id("run", session.session_id, idempotency_key)
        async with session.lock:
            mutation = await append_mutation(
                self._runtime,
                authorized,
                EvidenceAppend(
                    idempotency_key=idempotency_key,
                    event_type="scenario-created",
                    body=request,
                    scenario_id=scenario_id,
                    run_id=run_id,
                    resource_id=scenario_id,
                ),
            )
            if mutation.replayed:
                resource = session.scenarios.get(scenario_id)
                if resource is None:
                    raise ProblemError(
                        503,
                        "session_state_unavailable",
                        "Session state unavailable",
                        "The replayed scenario state is unavailable.",
                    )
                return scenario_response(resource), True
            manifest, observation = self._runtime.scenario_factory.build(
                scenario_id,
                request.seed,
                request.fault_family,
                trusted_timestamp(self._runtime.clock),
            )
            resource = ScenarioResource(manifest, observation, run_id)
            session.scenarios[scenario_id] = resource
            session.runs[run_id] = RunResource(run_id, scenario_id)
            return scenario_response(resource), False

    async def list(self, authorized: AuthorizedSession) -> ScenarioListResponse:
        """List only the caller session's scenarios in stable creation order."""
        async with authorized.session.lock:
            return ScenarioListResponse(
                items=tuple(
                    scenario_response(item) for item in authorized.session.scenarios.values()
                )
            )

    async def get(self, authorized: AuthorizedSession, scenario_id: str) -> ScenarioResponse:
        """Read one caller-owned scenario without cross-session enumeration."""
        async with authorized.session.lock:
            resource = authorized.session.scenarios.get(scenario_id)
            if resource is None:
                raise ProblemError(
                    404,
                    "scenario_not_found",
                    "Scenario not found",
                    "The scenario does not exist in this live session.",
                )
            return scenario_response(resource)

    async def diagnose(
        self,
        authorized: AuthorizedSession,
        scenario_id: str,
        idempotency_key: str,
        request: EmptyRequest,
    ) -> tuple[DiagnosisResponse, bool]:
        """Diagnose one scenario and append its evidence event."""
        session = authorized.session
        async with session.lock:
            resource = session.scenarios.get(scenario_id)
            if resource is None:
                raise ProblemError(
                    404,
                    "scenario_not_found",
                    "Scenario not found",
                    "The scenario does not exist in this live session.",
                )
            mutation = await append_mutation(
                self._runtime,
                authorized,
                EvidenceAppend(
                    idempotency_key=idempotency_key,
                    event_type="scenario-diagnosed",
                    body=request,
                    scenario_id=scenario_id,
                    run_id=resource.run_id,
                    resource_id=stable_id("diagnosis", session.session_id, idempotency_key),
                ),
            )
            diagnosis = diagnose_fault(resource.observation)
            return (
                DiagnosisResponse(
                    scenario_id=scenario_id,
                    run_id=resource.run_id,
                    status=diagnosis.status,
                    primary_fault=diagnosis.primary_fault,
                    secondary_evidence=diagnosis.secondary_evidence,
                ),
                mutation.replayed,
            )

    async def propose_patch(
        self,
        authorized: AuthorizedSession,
        scenario_id: str,
        idempotency_key: str,
        patch: TypedPatch,
    ) -> tuple[PatchResponse, bool]:
        """Validate and retain one simulation-only typed patch."""
        session = authorized.session
        async with session.lock:
            scenario = session.scenarios.get(scenario_id)
            if scenario is None:
                raise ProblemError(
                    404,
                    "scenario_not_found",
                    "Scenario not found",
                    "The scenario does not exist in this live session.",
                )
            assessment = assess_patch(patch, scenario.manifest)
            match assessment:
                case PatchRejected(code=code):
                    raise ProblemError(
                        422,
                        code.value,
                        "Patch rejected",
                        "The typed patch is not valid for this scenario baseline.",
                    )
                case PatchAccepted(patch_hash=patch_hash):
                    pass
                case _:
                    assert_never(assessment)
            mutation = await append_mutation(
                self._runtime,
                authorized,
                EvidenceAppend(
                    idempotency_key=idempotency_key,
                    event_type="patch-proposed",
                    body=patch,
                    scenario_id=scenario_id,
                    run_id=scenario.run_id,
                    resource_id=patch.patch_id,
                ),
            )
            if mutation.replayed:
                resource = session.patches.get(patch.patch_id)
                if resource is None:
                    raise ProblemError(
                        503,
                        "session_state_unavailable",
                        "Session state unavailable",
                        "The replayed patch state is unavailable.",
                    )
                return PatchResponse(
                    patch=resource.patch, patch_hash=resource.patch_hash, run_id=resource.run_id
                ), True
            if patch.patch_id in session.patches:
                raise ProblemError(
                    409,
                    "patch_exists",
                    "Patch exists",
                    "The patch ID already exists in this live session.",
                )
            session.patches[patch.patch_id] = PatchResource(patch, patch_hash, scenario.run_id)
            session.runs[scenario.run_id] = replace(
                session.runs[scenario.run_id],
                patch_id=patch.patch_id,
            )
            return PatchResponse(patch=patch, patch_hash=patch_hash, run_id=scenario.run_id), False
