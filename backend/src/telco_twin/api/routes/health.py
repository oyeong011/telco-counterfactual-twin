"""Process liveness and safe dependency readiness routes."""
# pyright: reportUnusedFunction=false

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from telco_twin.api.contracts import HealthResponse, ReadyResponse
from telco_twin.api.runtime import ApiRuntime


def router(runtime: ApiRuntime) -> APIRouter:
    """Build operations probes over one runtime instance."""
    result = APIRouter(tags=["operations"])

    @result.get("/healthz")
    async def health() -> HealthResponse:
        return HealthResponse(status="live")

    @result.get(
        "/readyz",
        response_model=ReadyResponse,
        responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadyResponse}},
    )
    async def readiness() -> ReadyResponse | JSONResponse:
        body = ReadyResponse(
            status="ready" if runtime.available else "degraded",
            checks={"approval_authority": True, "state_store": runtime.available},
        )
        if runtime.available:
            return body
        return JSONResponse(status_code=503, content=body.model_dump(mode="json"))

    return result
