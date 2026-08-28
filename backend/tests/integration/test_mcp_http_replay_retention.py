"""Bounded MCP HTTP replay retention tests."""

from __future__ import annotations

import anyio

from telco_twin.mcp.asgi import McpAsgiApp

from .mcp_http_support import (
    append_pings,
    initialize_body,
    live_session,
    post_headers,
    request,
    retained_ids,
    sse_headers,
    sse_ids,
)


def test_http_replay_rejects_cursor_below_retained_event_floor() -> None:
    async def scenario() -> None:
        app = McpAsgiApp(
            allowed_origins=frozenset({"https://portfolio.example"}),
            max_session_replay_events=3,
        )
        created = await request(app, method="POST", headers=post_headers(), body=initialize_body())
        session_id = created.headers["mcp-session-id"]
        stream = await request(app, method="GET", headers=sse_headers(session_id))
        evicted_cursor = sse_ids(stream.body)[0]
        session = live_session(app, session_id)
        _ = append_pings(session, "s1", 10)
        event_ids = retained_ids(session, "s1")
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
        created = await request(app, method="POST", headers=post_headers(), body=initialize_body())
        session_id = created.headers["mcp-session-id"]
        stream_1 = await request(app, method="GET", headers=sse_headers(session_id))
        session = live_session(app, session_id)
        _ = append_pings(session, "s1", 10)
        stream_2 = await request(app, method="GET", headers=sse_headers(session_id))
        _ = append_pings(session, "s2", 10)
        stream_3 = await request(app, method="GET", headers=sse_headers(session_id))
        _ = append_pings(session, "s3", 10)
        evicted_replay = await request(
            app,
            method="GET",
            headers=sse_headers(session_id, sse_ids(stream_1.body)[0]),
        )

        assert evicted_replay.status == 404
        assert list(session.streams) == ["s2", "s3"]
        assert session.replay_event_count() <= 12
        assert sse_ids(stream_2.body)[-1].split(":")[1] == "s2"
        assert sse_ids(stream_3.body)[-1].split(":")[1] == "s3"

    anyio.run(scenario)


def test_http_session_aggregate_replay_cap_can_drop_empty_old_streams() -> None:
    async def scenario() -> None:
        app = McpAsgiApp(
            allowed_origins=frozenset({"https://portfolio.example"}),
            max_session_replay_events=0,
        )
        created = await request(app, method="POST", headers=post_headers(), body=initialize_body())
        session_id = created.headers["mcp-session-id"]
        stream = await request(app, method="GET", headers=sse_headers(session_id))
        evicted_replay = await request(
            app,
            method="GET",
            headers=sse_headers(session_id, sse_ids(stream.body)[0]),
        )

        assert stream.status == 200
        assert evicted_replay.status == 404
        assert live_session(app, session_id).streams == {}

    anyio.run(scenario)


def test_http_replay_ping_injection_rejects_unknown_stream() -> None:
    async def scenario() -> None:
        app = McpAsgiApp(allowed_origins=frozenset({"https://portfolio.example"}))
        created = await request(app, method="POST", headers=post_headers(), body=initialize_body())
        session_id = created.headers["mcp-session-id"]

        assert live_session(app, session_id).append_ping("missing-stream") is None

    anyio.run(scenario)


def test_http_replay_stress_keeps_session_aggregate_window_bounded() -> None:
    async def scenario() -> None:
        app = McpAsgiApp(
            allowed_origins=frozenset({"https://portfolio.example"}),
            max_retained_streams=40,
            max_session_replay_events=256,
        )
        created = await request(app, method="POST", headers=post_headers(), body=initialize_body())
        session_id = created.headers["mcp-session-id"]
        first_stream = await request(app, method="GET", headers=sse_headers(session_id))
        session = live_session(app, session_id)
        _ = append_pings(session, "s1", 10)
        for _ in range(39):
            stream = await request(app, method="GET", headers=sse_headers(session_id))
            _ = append_pings(session, sse_ids(stream.body)[0].split(":")[1], 10)
        oldest_stream = next(iter(session.streams.values()))
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
        assert len(session.streams) <= 40
        assert session.replay_event_count() <= 256

    anyio.run(scenario)
