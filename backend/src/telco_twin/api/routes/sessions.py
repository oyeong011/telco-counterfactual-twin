"""Synthetic-only bounded demo-session bootstrap route."""
# pyright: reportUnusedFunction=false

from fastapi import APIRouter, Request, status

from telco_twin.api.contracts import DemoSessionRequest, DemoSessionResponse
from telco_twin.api.dependencies import bootstrap_guard
from telco_twin.api.runtime import ApiRuntime


def router(runtime: ApiRuntime) -> APIRouter:
    """Build the sole unauthenticated API bootstrap route."""
    result = APIRouter(prefix="/api", tags=["demo-sessions"])

    @result.post(
        "/demo-sessions",
        status_code=status.HTTP_201_CREATED,
    )
    async def create_demo_session(
        body: DemoSessionRequest,
        request: Request,
    ) -> DemoSessionResponse:
        _ = body
        await bootstrap_guard(runtime, request)
        return await runtime.create_demo_session()

    return result
