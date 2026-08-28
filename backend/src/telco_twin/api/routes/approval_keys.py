"""Public approval-root discovery route."""
# pyright: reportUnusedFunction=false

from fastapi import APIRouter

from telco_twin.api.runtime import ApiRuntime
from telco_twin.domain.approval import RootDescriptor


def router(runtime: ApiRuntime) -> APIRouter:
    """Build the public-key-only approval-root route."""
    result = APIRouter(tags=["approval-keys"])

    @result.get("/.well-known/approval-root")
    async def approval_root() -> RootDescriptor:
        return runtime.authority.descriptor

    return result
