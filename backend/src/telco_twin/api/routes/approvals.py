"""Approval request read and evidence-only decision routes."""
# pyright: reportUnusedFunction=false

from typing import Annotated, assert_never

from fastapi import APIRouter, Depends, Header, Path, Response

from telco_twin.api.approval_lifecycle import ApprovalLifecycle
from telco_twin.api.contracts import ApprovalDecisionResponse, ApprovalReadResponse, EmptyRequest
from telco_twin.api.dependencies import (
    ApprovalHeaders,
    DemoApprovalActor,
    JwtApprovalActor,
    approval_actor,
    approval_headers,
    authorized_session,
    mark_replay,
    require_idempotency_key,
)
from telco_twin.api.jwt_approval_lifecycle import JwtApprovalLifecycle
from telco_twin.api.runtime import ApiRuntime
from telco_twin.domain.approval import ApprovalDecision

DemoHeader = Annotated[str | None, Header(alias="X-Demo-Session-Token")]
HeadersDep = Annotated[ApprovalHeaders, Depends(approval_headers)]


def router(runtime: ApiRuntime) -> APIRouter:
    """Build pending request reads and signed terminal decisions."""
    result = APIRouter(prefix="/api/approval-requests", tags=["approvals"])
    lifecycle = ApprovalLifecycle(runtime)
    jwt_lifecycle = JwtApprovalLifecycle(runtime)

    @result.get("/{id}")
    async def get_approval_request(
        resource_id: Annotated[str, Path(alias="id")],
        demo_token: DemoHeader = None,
    ) -> ApprovalReadResponse:
        return await lifecycle.get(
            await authorized_session(runtime, demo_token),
            resource_id,
        )

    async def decide(
        resource_id: str,
        body: EmptyRequest,
        response: Response,
        headers: ApprovalHeaders,
        decision: ApprovalDecision,
    ) -> ApprovalDecisionResponse:
        actor = await approval_actor(
            runtime,
            resource_id,
            headers.demo_token,
            headers.authorization,
        )
        key = require_idempotency_key(headers.idempotency)
        match actor:
            case DemoApprovalActor(authorized=authorized):
                result_body, replayed = await lifecycle.decide_demo(
                    authorized,
                    resource_id,
                    key,
                    body,
                    decision,
                )
            case JwtApprovalActor(session=session):
                result_body, replayed = await jwt_lifecycle.decide(
                    session,
                    resource_id,
                    key,
                    body,
                    decision,
                )
            case _:
                assert_never(actor)
        mark_replay(response, replayed)
        return result_body

    @result.post("/{id}/approve")
    async def approve(
        resource_id: Annotated[str, Path(alias="id")],
        body: EmptyRequest,
        response: Response,
        headers: HeadersDep,
    ) -> ApprovalDecisionResponse:
        return await decide(
            resource_id,
            body,
            response,
            headers,
            ApprovalDecision.APPROVED,
        )

    @result.post("/{id}/reject")
    async def reject(
        resource_id: Annotated[str, Path(alias="id")],
        body: EmptyRequest,
        response: Response,
        headers: HeadersDep,
    ) -> ApprovalDecisionResponse:
        return await decide(
            resource_id,
            body,
            response,
            headers,
            ApprovalDecision.REJECTED,
        )

    return result
