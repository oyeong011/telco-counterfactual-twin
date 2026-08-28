"""ASGI MCP tool-call smoke tests."""

from __future__ import annotations

import anyio

from .mcp_http_support import initialized_app, json_map, json_map_value, post_headers, request


def test_tool_errors_are_returned_as_json_rpc_errors() -> None:
    async def scenario() -> None:
        app, session_id = await initialized_app()

        response = await request(
            app,
            method="POST",
            headers=post_headers(session_id),
            body={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "execute_patch", "arguments": {}},
            },
        )

        body = json_map(response.body)
        error = json_map_value(body["error"])
        assert response.status == 400
        assert error["data"] == "unknown_tool"

    anyio.run(scenario)
