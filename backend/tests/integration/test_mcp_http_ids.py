"""JSON-RPC id boundary tests for MCP HTTP."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import anyio

from telco_twin.mcp.asgi import McpAsgiApp

from .mcp_http_support import post_headers, request

if TYPE_CHECKING:
    from telco_twin.mcp.contracts import JsonMap, JsonValue


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
            body = _json_map(response.body)
            assert body["id"] is None
            error = _json_map(body["error"])
            assert error["code"] == -32600
            assert error["data"] == "bad_json_rpc"

    anyio.run(scenario)


def _json_map(payload: bytes | JsonValue) -> JsonMap:
    value = json.loads(payload) if isinstance(payload, bytes) else payload
    assert isinstance(value, dict)
    return value
