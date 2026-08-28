"""Patch-to-simulation route."""
# pyright: reportUnusedFunction=false

from typing import Annotated

from fastapi import APIRouter, Header, Path, Response, status

from telco_twin.api.contracts import EmptyRequest, SimulationResponse
from telco_twin.api.dependencies import authorized_session, mark_replay, require_idempotency_key
from telco_twin.api.runtime import ApiRuntime
from telco_twin.api.simulation_lifecycle import SimulationLifecycle


def router(runtime: ApiRuntime) -> APIRouter:
    """Build the deterministic simulation command route."""
    result = APIRouter(prefix="/api/patches", tags=["simulations"])
    lifecycle = SimulationLifecycle(runtime)

    @result.post("/{id}/simulations", status_code=status.HTTP_201_CREATED)
    async def create_simulation(
        resource_id: Annotated[str, Path(alias="id")],
        body: EmptyRequest,
        response: Response,
        token: Annotated[str | None, Header(alias="X-Demo-Session-Token")] = None,
        idempotency: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> SimulationResponse:
        created, replayed = await lifecycle.create(
            await authorized_session(runtime, token),
            resource_id,
            require_idempotency_key(idempotency),
            body,
        )
        mark_replay(response, replayed)
        return created

    return result
