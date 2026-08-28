"""Canonical runtime build-identity route."""
# pyright: reportUnusedFunction=false

from fastapi import APIRouter

from telco_twin.api.runtime import ApiRuntime
from telco_twin.domain.build_info import ServiceBuildInfo


def router(runtime: ApiRuntime) -> APIRouter:
    """Build the read-only service identity route."""
    result = APIRouter(tags=["operations"])

    @result.get("/build-info")
    async def build_info() -> ServiceBuildInfo:
        return runtime.build_info

    return result
