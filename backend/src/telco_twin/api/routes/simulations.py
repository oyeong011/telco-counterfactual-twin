"""Simulation read, comparison, and approval-request routes."""
# pyright: reportUnusedFunction=false

from typing import Annotated

from fastapi import APIRouter, Header, Path, Response, status

from telco_twin.api.approval_lifecycle import ApprovalLifecycle
from telco_twin.api.contracts import (
    ApprovalRequestResponse,
    EmptyRequest,
    SimulationReadResponse,
)
from telco_twin.api.dependencies import authorized_session, mark_replay, require_idempotency_key
from telco_twin.api.runtime import ApiRuntime
from telco_twin.api.simulation_lifecycle import SimulationLifecycle

TokenHeader = Annotated[str | None, Header(alias="X-Demo-Session-Token")]
IdempotencyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


def router(runtime: ApiRuntime) -> APIRouter:
    """Build simulation result and downstream evidence routes."""
    result = APIRouter(prefix="/api/simulations", tags=["simulations"])
    simulations = SimulationLifecycle(runtime)
    approvals = ApprovalLifecycle(runtime)

    @result.get("/{id}")
    async def get_simulation(
        resource_id: Annotated[str, Path(alias="id")],
        token: TokenHeader = None,
    ) -> SimulationReadResponse:
        return await simulations.get(await authorized_session(runtime, token), resource_id)

    @result.post(
        "/{id}/approval-requests",
        status_code=status.HTTP_201_CREATED,
    )
    async def request_approval(
        resource_id: Annotated[str, Path(alias="id")],
        body: EmptyRequest,
        response: Response,
        token: TokenHeader = None,
        idempotency: IdempotencyHeader = None,
    ) -> ApprovalRequestResponse:
        approval, replayed = await approvals.create_request(
            await authorized_session(runtime, token),
            resource_id,
            require_idempotency_key(idempotency),
            body,
        )
        mark_replay(response, replayed)
        return approval

    return result
