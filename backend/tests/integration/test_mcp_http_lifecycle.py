"""Streamable HTTP lifecycle and session conformance tests."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import anyio

from telco_twin.mcp.asgi import McpAsgiApp
from telco_twin.mcp.contracts import MCP_PROTOCOL_VERSION

from .mcp_http_support import initialized_app, post_headers, request

if TYPE_CHECKING:
    from telco_twin.mcp.http_boundary import ReceiveMessage


def test_initialize_negotiates_session_then_tools_list_returns_json() -> None:
    async def scenario() -> None:
        app = McpAsgiApp(allowed_origins=frozenset({"https://portfolio.example"}))
        created = await request(app, method="POST", headers=post_headers(), body=_initialize())
        session_id = created.headers["mcp-session-id"]
        initialized = await request(
            app,
            method="POST",
            headers=post_headers(session_id),
            body={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        tools = await request(
            app,
            method="POST",
            headers=post_headers(session_id),
            body={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        )

        assert created.status == 200
        server_name = json.loads(created.body)["result"]["serverInfo"]["name"]
        assert server_name == "telco-counterfactual-twin"
        assert initialized.status == 202
        assert session_id.isascii()
        assert json.loads(tools.body)["result"]["tools"][0]["name"] == "list_scenarios"

    anyio.run(scenario)


def test_transport_matrix_rejects_bad_headers_and_handles_notifications_delete() -> None:
    async def scenario() -> None:
        app, session_id = await initialized_app()
        bad_origin = await request(
            app,
            method="POST",
            headers=[(b"origin", b"https://evil.example"), (b"accept", b"application/json")],
            body={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        )
        missing_session = await request(
            app,
            method="POST",
            headers=post_headers(),
            body={"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
        )
        response_message = await request(
            app,
            method="POST",
            headers=post_headers(session_id),
            body={"jsonrpc": "2.0", "id": 99, "result": {}},
        )
        deleted = await request(app, method="DELETE", headers=post_headers(session_id))
        expired = await request(
            app,
            method="POST",
            headers=post_headers(session_id),
            body={"jsonrpc": "2.0", "id": 4, "method": "tools/list"},
        )

        assert bad_origin.status == 403
        assert missing_session.status == 400
        assert response_message.status == 202
        assert response_message.body == b""
        assert deleted.status == 204
        assert expired.status == 404

    anyio.run(scenario)


def test_http_rejects_operations_until_initialized_notification() -> None:
    async def scenario() -> None:
        app = McpAsgiApp(allowed_origins=frozenset({"https://portfolio.example"}))
        created = await request(app, method="POST", headers=post_headers(), body=_initialize())
        session_id = created.headers["mcp-session-id"]

        response = await request(
            app,
            method="POST",
            headers=post_headers(session_id),
            body={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        )

        assert response.status == 400
        assert json.loads(response.body)["error"]["data"] == "not_initialized"

    anyio.run(scenario)


def test_lifespan_shutdown_completes_and_clears_sessions() -> None:
    async def scenario() -> None:
        app, session_id = await initialized_app()
        sent: list[dict[str, Any]] = []
        messages: list[ReceiveMessage] = [
            {"type": "lifespan.startup"},
            {"type": "lifespan.shutdown"},
        ]
        message_iter = iter(messages)

        async def receive() -> ReceiveMessage:
            return next(message_iter)

        async def send(message: dict[str, Any]) -> None:
            sent.append(message)

        await app({"type": "lifespan"}, receive, send)

        assert [message["type"] for message in sent] == [
            "lifespan.startup.complete",
            "lifespan.shutdown.complete",
        ]
        assert session_id not in app._sessions

    anyio.run(scenario)


def test_http_scope_and_lifespan_fallbacks_are_closed() -> None:
    async def scenario() -> None:
        app = McpAsgiApp(allowed_origins=frozenset({"https://portfolio.example"}))
        sent: list[dict[str, Any]] = []

        async def receive() -> ReceiveMessage:
            return {"type": "lifespan.other"}

        async def send(message: dict[str, Any]) -> None:
            sent.append(message)

        await app({"type": "websocket"}, receive, send)
        await app({"type": "lifespan"}, receive, send)

        assert sent[0]["status"] == 500
        assert sent[-1]["type"] == "lifespan.shutdown.complete"

    anyio.run(scenario)


def _initialize() -> dict[str, Any]:
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
