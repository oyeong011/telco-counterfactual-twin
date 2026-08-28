"""Streamable HTTP SSE replay invariants."""

from __future__ import annotations

import anyio

from telco_twin.mcp.asgi import McpAsgiApp
from telco_twin.mcp.contracts import MCP_PROTOCOL_VERSION

from .mcp_http_support import (
    append_pings,
    initialize_body,
    initialized_app,
    live_session,
    post_headers,
    request,
    retained_ids,
    sse_headers,
    sse_ids,
    stream_token,
)


def test_get_requires_sse_accept_and_last_event_id_is_session_scoped() -> None:
    async def scenario() -> None:
        app, session_id = await initialized_app()
        missing_accept = await request(
            app,
            method="GET",
            headers=[
                (b"origin", b"https://portfolio.example"),
                (b"accept", b"application/json"),
                (b"mcp-session-id", session_id.encode()),
                (b"mcp-protocol-version", MCP_PROTOCOL_VERSION.encode()),
            ],
        )
        stream = await request(app, method="GET", headers=sse_headers(session_id))
        event_id = sse_ids(stream.body)[0]
        _ = append_pings(live_session(app, session_id), "s1", 1)
        replay = await request(app, method="GET", headers=sse_headers(session_id, event_id))
        cross_session = await request(
            app,
            method="GET",
            headers=sse_headers(session_id, f"other:{event_id}"),
        )

        assert missing_accept.status == 400
        assert stream.status == 200
        assert replay.status == 200
        assert event_id not in sse_ids(replay.body)
        assert b'"jsonrpc":"2.0"' in replay.body
        assert b'"method":"ping"' in stream.body
        assert cross_session.status == 404

    anyio.run(scenario)


def test_get_replay_compares_same_session_event_sequences_numerically_after_nine() -> None:
    async def scenario() -> None:
        app, session_id = await initialized_app()
        _ = await request(app, method="GET", headers=sse_headers(session_id))
        session = live_session(app, session_id)
        _ = append_pings(session, "s1", 10)
        event_ids = retained_ids(session, "s1")

        replay = await request(app, method="GET", headers=sse_headers(session_id, event_ids[8]))

        assert replay.status == 200
        assert event_ids[9] in sse_ids(replay.body)
        assert event_ids[10] in sse_ids(replay.body)

    anyio.run(scenario)


def test_post_json_responses_are_not_replay_events_but_get_sse_streams_are() -> None:
    async def scenario() -> None:
        app, session_id = await initialized_app()
        post_response = await request(
            app,
            method="POST",
            headers=post_headers(session_id),
            body={"jsonrpc": "2.0", "id": 70, "method": "tools/list"},
        )
        stream_a = await request(app, method="GET", headers=sse_headers(session_id))
        session = live_session(app, session_id)
        _ = append_pings(session, "s1", 10)
        stream_b = await request(app, method="GET", headers=sse_headers(session_id))
        stream_a_ids = retained_ids(session, "s1")
        cursor = stream_a_ids[8]
        replay_a = await request(app, method="GET", headers=sse_headers(session_id, cursor))

        assert "mcp-event-id" not in post_response.headers
        assert b'"id":70' not in stream_a.body
        assert sse_ids(replay_a.body) == stream_a_ids[9:]
        assert stream_token(stream_b.body) not in replay_a.body.decode()

    anyio.run(scenario)


def test_http_unknown_session_expiry_and_resume_after_cursor_fail_closed() -> None:
    async def scenario() -> None:
        app, session_id = await initialized_app()
        stream = await request(app, method="GET", headers=sse_headers(session_id))
        first_event = sse_ids(stream.body)[0]
        second_event = append_pings(live_session(app, session_id), "s1", 1)[0]

        after_first = await request(app, method="GET", headers=sse_headers(session_id, first_event))
        unknown_delete = await request(
            app,
            method="DELETE",
            headers=post_headers("missing-session"),
        )
        stale_app = McpAsgiApp(
            allowed_origins=frozenset({"https://portfolio.example"}),
            ttl_seconds=-1,
        )
        stale = await request(
            stale_app,
            method="POST",
            headers=post_headers(),
            body=initialize_body(),
        )
        stale_session = stale.headers["mcp-session-id"]
        expired = await request(stale_app, method="GET", headers=sse_headers(stale_session))

        assert second_event in sse_ids(after_first.body)
        assert first_event not in sse_ids(after_first.body)
        assert unknown_delete.status == 404
        assert expired.status == 404
        assert stale_app.session(stale_session) is None

    anyio.run(scenario)


def test_http_sse_replay_window_is_per_stream_and_bounded() -> None:
    async def scenario() -> None:
        app = McpAsgiApp(
            allowed_origins=frozenset({"https://portfolio.example"}),
            max_stream_events=2,
        )
        created = await request(app, method="POST", headers=post_headers(), body=initialize_body())
        session_id = created.headers["mcp-session-id"]
        _ = await request(
            app,
            method="POST",
            headers=post_headers(session_id),
            body={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        stream = await request(app, method="GET", headers=sse_headers(session_id))
        evicted_cursor = sse_ids(stream.body)[0]
        session = live_session(app, session_id)
        _ = append_pings(session, "s1", 10)
        event_ids = retained_ids(session, "s1")
        evicted_replay = await request(
            app,
            method="GET",
            headers=sse_headers(session_id, evicted_cursor),
        )
        replay = await request(app, method="GET", headers=sse_headers(session_id, event_ids[-2]))
        malformed = await request(
            app,
            method="GET",
            headers=sse_headers(session_id, f"{session_id}:s1:not-a-number"),
        )
        noncanonical = await request(
            app,
            method="GET",
            headers=sse_headers(session_id, f"{session_id}:s1:01"),
        )
        unicode_decimal = await request(
            app,
            method="GET",
            headers=sse_headers(session_id, f"{session_id}:s1:\uff11\uff10"),
        )
        unicode_numeric = await request(
            app,
            method="GET",
            headers=sse_headers(session_id, f"{session_id}:s1:²"),
        )

        assert len(session.streams["s1"].events) == 2
        assert evicted_replay.status == 404
        assert event_ids[-1] in sse_ids(replay.body)
        assert event_ids[0] not in sse_ids(replay.body)
        assert malformed.status == 404
        assert noncanonical.status == 404
        assert unicode_decimal.status == 404
        assert unicode_numeric.status == 404

    anyio.run(scenario)
