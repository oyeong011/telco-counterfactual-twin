"""Deterministic simulation and comparison lifecycle."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, assert_never, final

from telco_twin.api.contracts import (
    ComparisonResponse,
    EmptyRequest,
    SimulationReadResponse,
    SimulationResponse,
)
from telco_twin.api.errors import ProblemError
from telco_twin.api.mutations import EvidenceAppend, append_mutation, stable_id
from telco_twin.api.runtime_models import ComparisonResource, SimulationResource
from telco_twin.counterfactual.comparison import compare_counterfactual
from telco_twin.counterfactual.runner import (
    CounterfactualRejected,
    CounterfactualRun,
    run_counterfactual,
)

if TYPE_CHECKING:
    from telco_twin.api.runtime import ApiRuntime, AuthorizedSession


def simulation_response(resource: SimulationResource) -> SimulationResponse:
    """Project one retained deterministic run into the public response."""
    return SimulationResponse(
        simulation_id=resource.simulation_id,
        scenario_id=resource.run.baseline_manifest.scenario.scenario_id,
        patch_id=resource.patch_id,
        run_id=resource.run_id,
        status="completed",
        trace_hash=resource.run.candidate_trace.trace_hash,
    )


@final
class SimulationLifecycle:
    """Own real counterfactual runs and their machine-checkable comparisons."""

    def __init__(self, runtime: ApiRuntime) -> None:
        """Bind the lifecycle to one process runtime."""
        self._runtime = runtime

    async def create(
        self,
        authorized: AuthorizedSession,
        patch_id: str,
        idempotency_key: str,
        request: EmptyRequest,
    ) -> tuple[SimulationResponse, bool]:
        """Run or replay one deterministic baseline/candidate simulation."""
        session = authorized.session
        simulation_id = stable_id("simulation", session.session_id, idempotency_key)
        async with session.lock:
            patch = session.patches.get(patch_id)
            if patch is None:
                raise ProblemError(
                    404,
                    "patch_not_found",
                    "Patch not found",
                    "The patch does not exist in this live session.",
                )
            scenario = session.scenarios[session.runs[patch.run_id].scenario_id]
            mutation = await append_mutation(
                self._runtime,
                authorized,
                EvidenceAppend(
                    idempotency_key=idempotency_key,
                    event_type="simulation-completed",
                    body=request,
                    scenario_id=scenario.manifest.scenario.scenario_id,
                    run_id=patch.run_id,
                    resource_id=simulation_id,
                ),
            )
            if mutation.replayed:
                resource = session.simulations.get(simulation_id)
                if resource is None:
                    raise ProblemError(
                        503,
                        "session_state_unavailable",
                        "Session state unavailable",
                        "The replayed simulation state is unavailable.",
                    )
                return simulation_response(resource), True
            outcome = run_counterfactual(scenario.manifest, patch.patch)
            match outcome:
                case CounterfactualRejected(assessment=assessment):
                    raise ProblemError(
                        422,
                        assessment.code.value,
                        "Simulation rejected",
                        "The simulator rejected the typed patch.",
                    )
                case CounterfactualRun():
                    run = outcome
                case _:
                    assert_never(outcome)
            resource = SimulationResource(simulation_id, patch.run_id, patch_id, run)
            session.simulations[simulation_id] = resource
            session.runs[patch.run_id] = replace(
                session.runs[patch.run_id],
                simulation_id=simulation_id,
            )
            return simulation_response(resource), False

    async def get(
        self,
        authorized: AuthorizedSession,
        simulation_id: str,
    ) -> SimulationReadResponse:
        """Read a session-owned simulation and any completed comparison result."""
        async with authorized.session.lock:
            resource = authorized.session.simulations.get(simulation_id)
            if resource is None:
                raise ProblemError(
                    404,
                    "simulation_not_found",
                    "Simulation not found",
                    "The simulation does not exist in this live session.",
                )
            run = authorized.session.runs[resource.run_id]
            comparison = (
                authorized.session.comparisons.get(run.comparison_id)
                if run.comparison_id is not None
                else None
            )
            return SimulationReadResponse(
                simulation=simulation_response(resource),
                result=comparison.comparison.result if comparison is not None else None,
            )

    async def compare(
        self,
        authorized: AuthorizedSession,
        simulation_id: str,
        idempotency_key: str,
        request: EmptyRequest,
    ) -> tuple[ComparisonResponse, bool]:
        """Create or replay one baseline/candidate comparison."""
        session = authorized.session
        comparison_id = stable_id("comparison", session.session_id, idempotency_key)
        async with session.lock:
            simulation = session.simulations.get(simulation_id)
            if simulation is None:
                raise ProblemError(
                    404,
                    "simulation_not_found",
                    "Simulation not found",
                    "The simulation does not exist in this live session.",
                )
            mutation = await append_mutation(
                self._runtime,
                authorized,
                EvidenceAppend(
                    idempotency_key=idempotency_key,
                    event_type="comparison-created",
                    body=request,
                    scenario_id=simulation.run.baseline_manifest.scenario.scenario_id,
                    run_id=simulation.run_id,
                    resource_id=comparison_id,
                ),
            )
            if mutation.replayed:
                resource = session.comparisons.get(comparison_id)
                if resource is None:
                    raise ProblemError(
                        503,
                        "session_state_unavailable",
                        "Session state unavailable",
                        "The replayed comparison state is unavailable.",
                    )
                return ComparisonResponse(
                    comparison_id=comparison_id,
                    run_id=resource.run_id,
                    comparison=resource.comparison,
                ), True
            comparison = compare_counterfactual(simulation.run, simulation_id)
            resource = ComparisonResource(
                comparison_id, simulation.run_id, simulation_id, comparison
            )
            session.comparisons[comparison_id] = resource
            session.runs[simulation.run_id] = replace(
                session.runs[simulation.run_id],
                comparison_id=comparison_id,
            )
            return ComparisonResponse(
                comparison_id=comparison_id, run_id=simulation.run_id, comparison=comparison
            ), False
