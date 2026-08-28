"""Streamable HTTP malformed request and header boundary tests."""

from __future__ import annotations

import json

import anyio

from telco_twin.mcp.asgi import McpAsgiApp
from telco_twin.mcp.contracts import MCP_PROTOCOL_VERSION

from .mcp_http_support import (
    chunked_request,
    initialized_app,
    post_headers,
    request,
)


def test_http_rejects_malformed_json_rpc_without_500() -> None:
    async def scenario() -> None:
        app, session_id = await initialized_app()

        bad_json = await request(
            app,
            method="POST",
            headers=post_headers(session_id),
            raw_body=b"{",
        )
        bad_version = await request(
            app,
            method="POST",
            headers=post_headers(),
            body={"jsonrpc": "1.0", "id": 2, "method": "initialize", "params": {}},
        )
        bad_args = await request(
            app,
            method="POST",
            headers=post_headers(session_id),
            body={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "get_scenario", "arguments": {"scenario_id": 1}},
            },
        )
        extra_args = await request(
            app,
            method="POST",
            headers=post_headers(session_id),
            body={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "list_scenarios", "arguments": {"unexpected": "x"}},
            },
        )

        assert bad_json.status == 400
        assert bad_version.status == 400
        assert bad_args.status == 400
        assert extra_args.status == 400
        assert json.loads(bad_args.body)["error"]["data"] == "bad_arguments"
        assert json.loads(extra_args.body)["error"]["data"] == "bad_arguments"

    anyio.run(scenario)


def test_http_boundary_aggregates_body_and_rejects_substring_media_types() -> None:
    async def scenario() -> None:
        app = McpAsgiApp(
            allowed_origins=frozenset({"https://portfolio.example"}),
            max_body_bytes=32,
        )
        full_initialize = json.dumps(_initialize()).encode()
        chunked = await chunked_request(
            McpAsgiApp(allowed_origins=frozenset({"https://portfolio.example"})),
            method="POST",
            headers=post_headers(),
            chunks=[full_initialize[:20], full_initialize[20:]],
        )
        oversized = await chunked_request(
            app,
            method="POST",
            headers=post_headers(),
            chunks=[full_initialize[:20], full_initialize[20:40]],
        )
        bad_content_type = await request(
            McpAsgiApp(allowed_origins=frozenset({"https://portfolio.example"})),
            method="POST",
            headers=[
                (b"origin", b"https://portfolio.example"),
                (b"accept", b"application/json, text/event-stream"),
                (b"content-type", b"text/plain"),
            ],
            body={"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {}},
        )
        misleading_accept = await request(
            McpAsgiApp(allowed_origins=frozenset({"https://portfolio.example"})),
            method="POST",
            headers=[
                (b"origin", b"https://portfolio.example"),
                (b"accept", b"application/jsonish, text/event-stream"),
                (b"content-type", b"application/json"),
            ],
            body={"jsonrpc": "2.0", "id": 3, "method": "initialize", "params": {}},
        )
        init_notification = await request(
            McpAsgiApp(allowed_origins=frozenset({"https://portfolio.example"})),
            method="POST",
            headers=post_headers(),
            body={key: value for key, value in _initialize().items() if key != "id"},
        )

        assert chunked.status == 200
        assert oversized.status == 413
        assert bad_content_type.status == 400
        assert misleading_accept.status == 400
        assert init_notification.status == 400
        assert "mcp-session-id" not in init_notification.headers

    anyio.run(scenario)


def test_http_negative_edges_cover_path_method_accept_and_initialize_validation() -> None:
    async def scenario() -> None:
        app, session_id = await initialized_app()

        wrong_path = await request(
            app,
            path="/wrong",
            method="POST",
            headers=post_headers(session_id),
            body={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        wrong_method = await request(app, method="PATCH", headers=post_headers(session_id))
        bad_accept = await request(
            app,
            method="POST",
            headers=[(b"origin", b"https://portfolio.example"), (b"accept", b"application/json")],
            body={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        )
        session_on_initialize = await request(
            app,
            method="POST",
            headers=post_headers(session_id),
            body=_initialize(),
        )
        missing_initialize_params = await request(
            McpAsgiApp(allowed_origins=frozenset({"https://portfolio.example"})),
            method="POST",
            headers=post_headers(),
            body={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "initialize",
                "params": {"protocolVersion": MCP_PROTOCOL_VERSION},
            },
        )

        assert wrong_path.status == 404
        assert wrong_method.status == 405
        assert bad_accept.status == 400
        assert session_on_initialize.status == 400
        assert missing_initialize_params.status == 400

    anyio.run(scenario)


def test_http_focused_negative_transitions_for_branch_contract() -> None:
    async def scenario() -> None:
        app, session_id = await initialized_app()
        cases = [
            await request(
                app,
                method="POST",
                headers=post_headers(session_id),
                body={"jsonrpc": "2.0", "method": "notifications/progress"},
            ),
            await request(
                McpAsgiApp(allowed_origins=frozenset({"https://portfolio.example"})),
                method="POST",
                headers=post_headers(),
                body={
                    "jsonrpc": "2.0",
                    "id": 30,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "1900-01-01",
                        "capabilities": {},
                        "clientInfo": {"name": "pytest", "version": "0"},
                    },
                },
            ),
            await request(
                app,
                method="POST",
                headers=post_headers(session_id),
                body={"jsonrpc": "2.0", "id": 31, "method": "tools/call", "params": {}},
            ),
            await request(
                app,
                method="POST",
                headers=post_headers(session_id),
                body={"jsonrpc": "2.0", "id": 32, "method": "tools/call", "params": []},
            ),
            await request(
                app,
                method="POST",
                headers=post_headers(session_id),
                body={
                    "jsonrpc": "2.0",
                    "id": 33,
                    "method": "tools/call",
                    "params": {"name": "list_scenarios", "arguments": []},
                },
            ),
            await request(app, method="POST", headers=post_headers(session_id), raw_body=b"[]"),
        ]

        assert [response.status for response in cases] == [202, 400, 400, 400, 400, 400]
        assert json.loads(cases[2].body)["error"]["data"] == "missing_tool_name"
        assert json.loads(cases[4].body)["error"]["data"] == "bad_arguments"

    anyio.run(scenario)


def test_http_initialize_session_cap_reaps_expired_before_rejecting_live_sessions() -> None:
    async def scenario() -> None:
        capped = McpAsgiApp(
            allowed_origins=frozenset({"https://portfolio.example"}),
            max_sessions=1,
            ttl_seconds=900,
        )
        first = await request(capped, method="POST", headers=post_headers(), body=_initialize())
        capped_out = await request(
            capped, method="POST", headers=post_headers(), body=_initialize()
        )
        stale = McpAsgiApp(
            allowed_origins=frozenset({"https://portfolio.example"}),
            max_sessions=1,
            ttl_seconds=-1,
        )
        expired = await request(stale, method="POST", headers=post_headers(), body=_initialize())
        reaped = await request(stale, method="POST", headers=post_headers(), body=_initialize())

        assert first.status == 200
        assert capped_out.status == 429
        assert expired.status == 200
        assert reaped.status == 200

    anyio.run(scenario)


def _initialize() -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "0"},
        },
    }
