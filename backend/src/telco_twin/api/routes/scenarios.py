"""Scenario, diagnosis, and typed-patch routes."""
# pyright: reportUnusedFunction=false

from typing import Annotated

from fastapi import APIRouter, Header, Path, Response, status

from telco_twin.api.contracts import (
    DiagnosisResponse,
    EmptyRequest,
    PatchResponse,
    ScenarioCreateRequest,
    ScenarioListResponse,
    ScenarioResponse,
)
from telco_twin.api.dependencies import (
    authorized_session,
    mark_replay,
    require_idempotency_key,
)
from telco_twin.api.runtime import ApiRuntime
from telco_twin.api.scenario_lifecycle import ScenarioLifecycle
from telco_twin.domain.intervention import TypedPatch

TokenHeader = Annotated[str | None, Header(alias="X-Demo-Session-Token")]
IdempotencyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


def router(runtime: ApiRuntime) -> APIRouter:
    """Build scenario lifecycle routes over one service instance."""
    result = APIRouter(prefix="/api/scenarios", tags=["scenarios"])
    lifecycle = ScenarioLifecycle(runtime)

    @result.get("")
    async def list_scenarios(
        token: TokenHeader = None,
    ) -> ScenarioListResponse:
        return await lifecycle.list(await authorized_session(runtime, token))

    @result.post("", status_code=status.HTTP_201_CREATED)
    async def create_scenario(
        body: ScenarioCreateRequest,
        response: Response,
        token: TokenHeader = None,
        idempotency: IdempotencyHeader = None,
    ) -> ScenarioResponse:
        authorized = await authorized_session(runtime, token)
        created, replayed = await lifecycle.create(
            authorized,
            require_idempotency_key(idempotency),
            body,
        )
        mark_replay(response, replayed)
        return created

    @result.get("/{id}")
    async def get_scenario(
        resource_id: Annotated[str, Path(alias="id")],
        token: TokenHeader = None,
    ) -> ScenarioResponse:
        return await lifecycle.get(await authorized_session(runtime, token), resource_id)

    @result.post("/{id}/diagnose")
    async def diagnose_scenario(
        resource_id: Annotated[str, Path(alias="id")],
        body: EmptyRequest,
        response: Response,
        token: TokenHeader = None,
        idempotency: IdempotencyHeader = None,
    ) -> DiagnosisResponse:
        diagnosis, replayed = await lifecycle.diagnose(
            await authorized_session(runtime, token),
            resource_id,
            require_idempotency_key(idempotency),
            body,
        )
        mark_replay(response, replayed)
        return diagnosis

    @result.post("/{id}/patches", status_code=201)
    async def propose_patch(
        resource_id: Annotated[str, Path(alias="id")],
        body: TypedPatch,
        response: Response,
        token: TokenHeader = None,
        idempotency: IdempotencyHeader = None,
    ) -> PatchResponse:
        patch, replayed = await lifecycle.propose_patch(
            await authorized_session(runtime, token),
            resource_id,
            require_idempotency_key(idempotency),
            body,
        )
        mark_replay(response, replayed)
        return patch

    return result
