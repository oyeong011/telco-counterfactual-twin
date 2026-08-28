"""Streamable HTTP Origin allowlist tests."""

from __future__ import annotations

import anyio

from telco_twin.mcp.asgi import McpAsgiApp
from telco_twin.mcp.contracts import MCP_PROTOCOL_VERSION

from .mcp_http_support import initialize_body, post_headers, request


def test_http_requires_configured_origin_on_post_get_and_delete() -> None:
    async def scenario() -> None:
        app = McpAsgiApp(allowed_origins=frozenset({"https://portfolio.example"}))
        missing_origin_post = await request(
            app,
            method="POST",
            headers=[
                (b"accept", b"application/json, text/event-stream"),
                (b"content-type", b"application/json"),
            ],
            body=initialize_body(),
        )
        initialized = await request(
            app,
            method="POST",
            headers=post_headers(),
            body=initialize_body(),
        )
        session_id = initialized.headers["mcp-session-id"]
        missing_origin_get = await request(
            app,
            method="GET",
            headers=[
                (b"accept", b"text/event-stream"),
                (b"mcp-session-id", session_id.encode()),
                (b"mcp-protocol-version", MCP_PROTOCOL_VERSION.encode()),
            ],
        )
        missing_origin_delete = await request(
            app,
            method="DELETE",
            headers=[
                (b"mcp-session-id", session_id.encode()),
                (b"mcp-protocol-version", MCP_PROTOCOL_VERSION.encode()),
            ],
        )

        assert missing_origin_post.status == 403
        assert missing_origin_get.status == 403
        assert missing_origin_delete.status == 403

    anyio.run(scenario)
