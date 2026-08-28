"""Run-scoped SSE and downloadable evidence routes."""
# pyright: reportUnusedFunction=false

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Header, Path
from fastapi.responses import StreamingResponse

from telco_twin.api.contracts import EvidenceResponse
from telco_twin.api.dependencies import authorized_session
from telco_twin.api.evidence_lifecycle import EvidenceLifecycle
from telco_twin.api.runtime import ApiRuntime
from telco_twin.simulator.frozen_event import FrozenEvent

TokenHeader = Annotated[str | None, Header(alias="X-Demo-Session-Token")]
LastEventHeader = Annotated[str | None, Header(alias="Last-Event-ID")]


async def _event_stream(events: tuple[FrozenEvent, ...]) -> AsyncIterator[bytes]:
    for event in events:
        yield (
            f"id: {event.event_id}\nevent: {event.event_type}\ndata: {event.model_dump_json()}\n\n"
        ).encode()
    yield b": heartbeat\n\n"


def router(runtime: ApiRuntime) -> APIRouter:
    """Build bounded replay and evidence download routes."""
    result = APIRouter(prefix="/api/runs", tags=["runs"])
    lifecycle = EvidenceLifecycle(runtime)

    @result.get("/{id}/events", response_class=StreamingResponse)
    async def run_events(
        resource_id: Annotated[str, Path(alias="id")],
        token: TokenHeader = None,
        last_event_id: LastEventHeader = None,
    ) -> StreamingResponse:
        events = await lifecycle.reconnect(
            await authorized_session(runtime, token),
            resource_id,
            last_event_id,
        )
        return StreamingResponse(
            _event_stream(events),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
            },
        )

    @result.get("/{id}/evidence")
    async def run_evidence(
        resource_id: Annotated[str, Path(alias="id")],
        token: TokenHeader = None,
    ) -> EvidenceResponse:
        return await lifecycle.evidence(
            await authorized_session(runtime, token),
            resource_id,
        )

    return result
