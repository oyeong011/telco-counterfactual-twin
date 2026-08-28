"""JSON-RPC id boundary tests for MCP HTTP."""

from __future__ import annotations

import anyio

from telco_twin.mcp.asgi import McpAsgiApp

from .mcp_http_support import json_map, json_map_value, post_headers, request


def test_http_rejects_present_malformed_json_rpc_ids() -> None:
    async def scenario() -> None:
        app = McpAsgiApp(allowed_origins=frozenset({"https://portfolio.example"}))
        cases = [
            await request(
                app,
                method="POST",
                headers=post_headers(),
                body={"jsonrpc": "2.0", "id": True, "method": "initialize", "params": {}},
            ),
            await request(
                app,
                method="POST",
                headers=post_headers(),
                body={"jsonrpc": "2.0", "id": None, "method": "initialize", "params": {}},
            ),
            await request(
                app,
                method="POST",
                headers=post_headers(),
                body={"jsonrpc": "2.0", "id": {"x": 1}, "method": "initialize", "params": {}},
            ),
            await request(
                app,
                method="POST",
                headers=post_headers(),
                body={"jsonrpc": "2.0", "id": [1], "method": "initialize", "params": {}},
            ),
        ]

        assert [response.status for response in cases] == [400, 400, 400, 400]
        for response in cases:
            body = json_map(response.body)
            assert body["id"] is None
            error = json_map_value(body["error"])
            assert error["code"] == -32600
            assert error["data"] == "bad_json_rpc"

    anyio.run(scenario)
