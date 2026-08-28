"""Bounded simulator determinism benchmark route."""
# pyright: reportUnusedFunction=false

from typing import Annotated

from fastapi import APIRouter, Header, Response

from telco_twin.api.benchmark_lifecycle import BenchmarkLifecycle
from telco_twin.api.contracts import BenchmarkRequest, BenchmarkResponse
from telco_twin.api.dependencies import authorized_session, mark_replay, require_idempotency_key
from telco_twin.api.runtime import ApiRuntime


def router(runtime: ApiRuntime) -> APIRouter:
    """Build the honest real-simulator benchmark route."""
    result = APIRouter(prefix="/api", tags=["benchmarks"])
    lifecycle = BenchmarkLifecycle(runtime)

    @result.post("/benchmarks")
    async def benchmark(
        body: BenchmarkRequest,
        response: Response,
        token: Annotated[str | None, Header(alias="X-Demo-Session-Token")] = None,
        idempotency: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> BenchmarkResponse:
        benchmark_response, replayed = await lifecycle.run(
            await authorized_session(runtime, token),
            require_idempotency_key(idempotency),
            body,
        )
        mark_replay(response, replayed)
        return benchmark_response

    return result
