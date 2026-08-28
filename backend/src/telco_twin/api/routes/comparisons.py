"""Simulation comparison command route."""
# pyright: reportUnusedFunction=false

from typing import Annotated

from fastapi import APIRouter, Header, Path, Response, status

from telco_twin.api.contracts import ComparisonResponse, EmptyRequest
from telco_twin.api.dependencies import authorized_session, mark_replay, require_idempotency_key
from telco_twin.api.runtime import ApiRuntime
from telco_twin.api.simulation_lifecycle import SimulationLifecycle


def router(runtime: ApiRuntime) -> APIRouter:
    """Build the baseline/candidate comparison route."""
    result = APIRouter(prefix="/api/simulations", tags=["comparisons"])
    lifecycle = SimulationLifecycle(runtime)

    @result.post("/{id}/comparisons", status_code=status.HTTP_201_CREATED)
    async def compare_simulation(
        resource_id: Annotated[str, Path(alias="id")],
        body: EmptyRequest,
        response: Response,
        token: Annotated[str | None, Header(alias="X-Demo-Session-Token")] = None,
        idempotency: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> ComparisonResponse:
        comparison, replayed = await lifecycle.compare(
            await authorized_session(runtime, token),
            resource_id,
            require_idempotency_key(idempotency),
            body,
        )
        mark_replay(response, replayed)
        return comparison

    return result
