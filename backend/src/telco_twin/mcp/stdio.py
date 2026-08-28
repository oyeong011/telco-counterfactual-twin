"""Newline-delimited stdio MCP adapter."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import TextIO

import anyio

from telco_twin.mcp.contracts import MCP_PROTOCOL_VERSION, JsonRpc, tool_contracts_json
from telco_twin.mcp.http_boundary import JsonRequest, RequestId, parse_request
from telco_twin.mcp.state import EvidenceMcpService, McpToolError

SUPPORTED_HANDSHAKE_VERSIONS = frozenset(
    {"2024-11-05", "2025-03-26", MCP_PROTOCOL_VERSION, "2025-11-25"}
)
SERVER_INFO: JsonRpc = {"name": "telco-counterfactual-twin", "version": "0.1.0"}


@dataclass(slots=True)
class StdioMcpServer:
    """Read JSON-RPC lines from stdin and write only JSON-RPC lines to stdout."""

    service: EvidenceMcpService = field(default_factory=EvidenceMcpService)
    awaiting_initialized: bool = False
    initialized: bool = False

    async def handle_line(self, line: str) -> str | None:
        """Handle one JSON-RPC request line."""
        response: str | None
        try:
            request = parse_request(line.encode())
        except McpToolError as exc:
            code = -32700 if exc.code == "bad_json" else -32600
            response = _error(None, code, exc.code, exc.message)
        else:
            response = await self._handle_parsed(request)
        return response

    async def _handle_parsed(self, request: JsonRequest) -> str | None:
        request_id = request.get("id")
        method = request.get("method")
        if not isinstance(method, str):
            return (
                None
                if "id" not in request
                else _error(request_id, -32600, "method", "method is required")
            )
        if "id" not in request:
            if method == "notifications/initialized" and self.awaiting_initialized:
                self.awaiting_initialized = False
                self.initialized = True
            return None
        try:
            result = await self._dispatch_request(request, method)
        except McpToolError as error:
            return _error(request_id, -32010, error.code, error.message)
        return json.dumps(
            {"jsonrpc": "2.0", "id": request_id, "result": result},
            separators=(",", ":"),
        )

    async def _dispatch_request(self, request: JsonRequest, method: str) -> JsonRpc:
        match method:
            case "initialize":
                if self.awaiting_initialized or self.initialized:
                    code = "already_initialized"
                    raise _mcp_error(code, "initialize is already complete")
                return self._initialize(request)
            case "tools/list":
                if not self.initialized:
                    code = "not_initialized"
                    raise _mcp_error(code, "initialize is incomplete")
                return {"tools": tool_contracts_json()}
            case "tools/call":
                if not self.initialized:
                    code = "not_initialized"
                    raise _mcp_error(code, "initialize is incomplete")
                return await self._tool_result(request)
            case _:
                code = "method"
                raise _mcp_error(code, "method not found")

    def _initialize(self, request: JsonRequest) -> JsonRpc:
        params = request.get("params")
        if not isinstance(params, dict):
            code = "bad_params"
            raise _mcp_error(code, "initialize params are required")
        if params.get("protocolVersion") not in SUPPORTED_HANDSHAKE_VERSIONS:
            code = "unsupported_version"
            raise _mcp_error(code, "protocol version is unsupported")
        if not isinstance(params.get("capabilities"), dict) or not isinstance(
            params.get("clientInfo"), dict
        ):
            code = "bad_params"
            raise _mcp_error(code, "capabilities and clientInfo are required")
        self.awaiting_initialized = True
        return {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        }

    async def _tool_result(self, request: JsonRequest) -> JsonRpc:
        params = request.get("params")
        if not isinstance(params, dict):
            code = "bad_arguments"
            raise _mcp_error(code, "params must be an object")
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not isinstance(arguments, dict):
            code = "bad_arguments"
            raise _mcp_error(code, "tool name and arguments are required")
        tool_result = await self.service.call_tool(name, arguments)
        return {"content": [{"type": "text", "text": json.dumps(tool_result, sort_keys=True)}]}

    async def run(self, stdin: TextIO, stdout: TextIO) -> None:
        """Run until stdin closes."""
        for line in stdin:
            response = await self.handle_line(line)
            if response is not None:
                _ = stdout.write(response)
                _ = stdout.write("\n")
                stdout.flush()


def main() -> None:
    """CLI entrypoint for local MCP clients."""
    anyio.run(StdioMcpServer().run, sys.stdin, sys.stdout)


def _error(request_id: RequestId, code: int, reason: str, message: str) -> str:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message, "data": reason},
        },
        separators=(",", ":"),
    )


def _mcp_error(code: str, message: str) -> McpToolError:
    return McpToolError(code, message)


if __name__ == "__main__":
    main()
