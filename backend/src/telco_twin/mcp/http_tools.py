"""JSON-RPC tool-call helpers for Streamable HTTP."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from telco_twin.mcp.state import EvidenceMcpService, McpToolError

if TYPE_CHECKING:
    from telco_twin.mcp.contracts import JsonRpc
    from telco_twin.mcp.http_boundary import JsonRequest


async def tool_result(service: EvidenceMcpService, request: JsonRequest) -> JsonRpc:
    """Return an MCP content result for one tools/call request."""
    params = request.get("params", {})
    if not isinstance(params, dict):
        code = "bad_arguments"
        raise McpToolError(code, "params must be an object")
    name = params.get("name")
    raw_arguments = params.get("arguments", {})
    if not isinstance(name, str):
        code = "missing_tool_name"
        raise McpToolError(code, "tool name is required")
    if not isinstance(raw_arguments, dict):
        code = "bad_arguments"
        raise McpToolError(code, "arguments must be an object")
    result = await service.call_tool(name, raw_arguments)
    return {"content": [{"type": "text", "text": json.dumps(result, sort_keys=True)}]}
