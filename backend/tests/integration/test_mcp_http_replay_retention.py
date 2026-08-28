"""Bounded MCP HTTP replay retention tests."""

from __future__ import annotations

import anyio

from telco_twin.mcp.asgi import McpAsgiApp
from telco_twin.mcp.contracts import MCP_PROTOCOL_VERSION

from .mcp_http_support import post_headers, request, sse_headers, sse_ids


def test_http_replay_rejects_cursor_below_retained_event_floor() -> None:
    async def scenario() -> None:
        app = McpAsgiApp(
            allowed_origins=frozenset({"https://portfolio.example"}),
            max_session_replay_events=3,
        )
        created = await request(app, method="POST", headers=post_headers(), body=_initialize())
        session_id = created.headers["mcp-session-id"]
        stream = await request(app, method="GET", headers=sse_headers(session_id))
        evicted_cursor = sse_ids(stream.body)[0]
        _append_pings(app, session_id, "s1", 10)
        event_ids = _retained_ids(app, session_id, "s1")
        replay_from_evicted = await request(
            app,
            method="GET",
            headers=sse_headers(session_id, evicted_cursor),
        )
        replay_from_retained = await request(
            app,
            method="GET",
            headers=sse_headers(session_id, event_ids[0]),
        )

        assert replay_from_evicted.status == 404
        assert replay_from_retained.status == 200
        assert sse_ids(replay_from_retained.body) == event_ids[1:]

    anyio.run(scenario)


def test_http_session_evicts_old_streams_and_caps_aggregate_replay_events() -> None:
    async def scenario() -> None:
        app = McpAsgiApp(
            allowed_origins=frozenset({"https://portfolio.example"}),
            max_retained_streams=2,
            max_session_replay_events=12,
        )
        created = await request(app, method="POST", headers=post_headers(), body=_initialize())
        session_id = created.headers["mcp-session-id"]
        stream_1 = await request(app, method="GET", headers=sse_headers(session_id))
        _append_pings(app, session_id, "s1", 10)
        stream_2 = await request(app, method="GET", headers=sse_headers(session_id))
        _append_pings(app, session_id, "s2", 10)
        stream_3 = await request(app, method="GET", headers=sse_headers(session_id))
        _append_pings(app, session_id, "s3", 10)
        evicted_replay = await request(
            app,
            method="GET",
            headers=sse_headers(session_id, sse_ids(stream_1.body)[0]),
        )
        live_session = app._sessions[session_id]

        assert evicted_replay.status == 404
        assert list(live_session.streams) == ["s2", "s3"]
        assert live_session.replay_event_count() <= 12
        assert sse_ids(stream_2.body)[-1].split(":")[1] == "s2"
        assert sse_ids(stream_3.body)[-1].split(":")[1] == "s3"

    anyio.run(scenario)


def test_http_session_aggregate_replay_cap_can_drop_empty_old_streams() -> None:
    async def scenario() -> None:
        app = McpAsgiApp(
            allowed_origins=frozenset({"https://portfolio.example"}),
            max_session_replay_events=0,
        )
        created = await request(app, method="POST", headers=post_headers(), body=_initialize())
        session_id = created.headers["mcp-session-id"]
        stream = await request(app, method="GET", headers=sse_headers(session_id))
        evicted_replay = await request(
            app,
            method="GET",
            headers=sse_headers(session_id, sse_ids(stream.body)[0]),
        )

        assert stream.status == 200
        assert evicted_replay.status == 404
        assert app._sessions[session_id].streams == {}

    anyio.run(scenario)


def test_http_replay_ping_injection_rejects_unknown_stream() -> None:
    async def scenario() -> None:
        app = McpAsgiApp(allowed_origins=frozenset({"https://portfolio.example"}))
        created = await request(app, method="POST", headers=post_headers(), body=_initialize())
        session_id = created.headers["mcp-session-id"]

        assert app._sessions[session_id].append_ping("missing-stream") is None

    anyio.run(scenario)


def test_http_replay_stress_keeps_session_aggregate_window_bounded() -> None:
    async def scenario() -> None:
        app = McpAsgiApp(
            allowed_origins=frozenset({"https://portfolio.example"}),
            max_retained_streams=40,
            max_session_replay_events=256,
        )
        created = await request(app, method="POST", headers=post_headers(), body=_initialize())
        session_id = created.headers["mcp-session-id"]
        first_stream = await request(app, method="GET", headers=sse_headers(session_id))
        _append_pings(app, session_id, "s1", 10)
        for _ in range(39):
            stream = await request(app, method="GET", headers=sse_headers(session_id))
            _append_pings(app, session_id, sse_ids(stream.body)[0].split(":")[1], 10)
        live_session = app._sessions[session_id]
        oldest_stream = next(iter(live_session.streams.values()))
        retained_floor = oldest_stream.events[0].event_id
        replay_from_evicted_stream = await request(
            app,
            method="GET",
            headers=sse_headers(session_id, sse_ids(first_stream.body)[0]),
        )
        replay_from_floor = await request(
            app,
            method="GET",
            headers=sse_headers(session_id, retained_floor),
        )

        assert replay_from_evicted_stream.status == 404
        assert replay_from_floor.status == 200
        assert len(live_session.streams) <= 40
        assert live_session.replay_event_count() <= 256

    anyio.run(scenario)


def _initialize() -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": 44,
        "method": "initialize",
        "params": {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "0"},
        },
    }


def _append_pings(
    app: McpAsgiApp,
    session_id: str,
    stream_id: str,
    count: int,
) -> list[str]:
    event_ids: list[str] = []
    for _ in range(count):
        frame = app._sessions[session_id].append_ping(stream_id)
        assert frame is not None
        event_ids.append(frame[0])
    return event_ids


def _retained_ids(app: McpAsgiApp, session_id: str, stream_id: str) -> list[str]:
    return [event.event_id for event in app._sessions[session_id].streams[stream_id].events]
