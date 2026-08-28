"""Stdio MCP lifecycle tests against the evidence-only adapter."""

from __future__ import annotations

import json
import sys
from io import StringIO
from pathlib import Path

import anyio
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from telco_twin.mcp.stdio import StdioMcpServer

from .mcp_client_flow_support import full_evidence_flow


def test_stdio_rejects_tools_list_before_initialize() -> None:
    async def scenario() -> None:
        server = StdioMcpServer()

        notification = await server.handle_line(
            '{"jsonrpc":"2.0","method":"notifications/initialized"}'
        )
        response = await server.handle_line('{"jsonrpc":"2.0","id":1,"method":"tools/list"}')

        assert notification is None
        assert response is not None
        body = json.loads(response)
        assert body["error"]["data"] == "not_initialized"

    anyio.run(scenario)


def test_stdio_initialize_includes_server_info_and_notifications_are_silent() -> None:
    async def scenario() -> None:
        server = StdioMcpServer()

        initialized = await server.handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "pytest", "version": "0"},
                    },
                }
            )
        )
        notification = await server.handle_line(
            '{"jsonrpc":"2.0","method":"notifications/initialized"}'
        )
        tools = await server.handle_line('{"jsonrpc":"2.0","id":2,"method":"tools/list"}')

        assert initialized is not None
        body = json.loads(initialized)
        assert body["result"]["serverInfo"]["name"] == "telco-counterfactual-twin"
        assert notification is None
        assert tools is not None
        assert json.loads(tools)["result"]["tools"][0]["name"] == "list_scenarios"

    anyio.run(scenario)


def test_stdio_rejects_present_malformed_json_rpc_ids() -> None:
    async def scenario() -> None:
        server = StdioMcpServer()
        cases = [
            await server.handle_line('{"jsonrpc":"2.0","id":true,"method":"tools/list"}'),
            await server.handle_line('{"jsonrpc":"2.0","id":null,"method":"tools/list"}'),
            await server.handle_line('{"jsonrpc":"2.0","id":{"x":1},"method":"tools/list"}'),
            await server.handle_line('{"jsonrpc":"2.0","id":[1],"method":"tools/list"}'),
        ]

        assert all(response is not None for response in cases)
        for response in cases:
            assert response is not None
            body = json.loads(response)
            assert body["id"] is None
            assert body["error"]["code"] == -32600
            assert body["error"]["data"] == "bad_json_rpc"

    anyio.run(scenario)


def test_real_mcp_stdio_client_completes_full_evidence_flow() -> None:
    async def scenario() -> None:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "telco_twin.mcp.stdio"],
            cwd=Path.cwd(),
        )
        async with (
            stdio_client(params) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            result = await session.initialize()
            tools = await session.list_tools()
            approval = await full_evidence_flow(session)

        assert result.server_info.name == "telco-counterfactual-twin"
        assert [tool.name for tool in tools.tools][:1] == ["list_scenarios"]
        assert approval["network_change_permitted"] is False

    anyio.run(scenario)


def test_stdio_malformed_and_bad_lifecycle_inputs_fail_closed() -> None:
    async def scenario() -> None:
        server = StdioMcpServer()

        malformed = await server.handle_line("{")
        bad_rpc = await server.handle_line("[]")
        silent_response = await server.handle_line('{"jsonrpc":"2.0","result":{}}')
        missing_method = await server.handle_line('{"jsonrpc":"2.0","id":2,"result":{}}')
        unsupported = await server.handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "1900-01-01",
                        "capabilities": {},
                        "clientInfo": {"name": "pytest", "version": "0"},
                    },
                }
            )
        )
        missing_params = await server.handle_line('{"jsonrpc":"2.0","id":4,"method":"initialize"}')

        assert malformed is not None
        assert json.loads(malformed)["error"]["data"] == "bad_json"
        assert bad_rpc is not None
        assert json.loads(bad_rpc)["error"]["data"] == "bad_json_rpc"
        assert silent_response is None
        assert missing_method is not None
        assert json.loads(missing_method)["error"]["data"] == "method"
        assert unsupported is not None
        assert json.loads(unsupported)["error"]["data"] == "unsupported_version"
        assert missing_params is not None
        assert json.loads(missing_params)["error"]["data"] == "bad_params"

    anyio.run(scenario)


def test_stdio_tool_call_errors_and_run_skip_notification_output() -> None:
    async def scenario() -> None:
        server = StdioMcpServer()
        _ = await server.handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "pytest", "version": "0"},
                    },
                }
            )
        )
        _ = await server.handle_line('{"jsonrpc":"2.0","method":"notifications/initialized"}')

        duplicate_initialize = await server.handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "pytest", "version": "0"},
                    },
                }
            )
        )
        preinit_call = await StdioMcpServer().handle_line(
            '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"list_scenarios","arguments":{}}}'
        )
        bad_params = await server.handle_line(
            '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":[]}'
        )
        bad_name = await server.handle_line(
            '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"arguments":{}}}'
        )
        unknown = await server.handle_line('{"jsonrpc":"2.0","id":4,"method":"unknown/method"}')
        stdin = StringIO(
            '{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
            '{"jsonrpc":"2.0","id":5,"method":"tools/list"}\n'
        )
        stdout = StringIO()
        await server.run(stdin, stdout)

        assert duplicate_initialize is not None
        assert json.loads(duplicate_initialize)["error"]["data"] == "already_initialized"
        assert preinit_call is not None
        assert json.loads(preinit_call)["error"]["data"] == "not_initialized"
        assert bad_params is not None
        assert json.loads(bad_params)["error"]["data"] == "bad_arguments"
        assert bad_name is not None
        assert json.loads(bad_name)["error"]["data"] == "bad_arguments"
        assert unknown is not None
        assert json.loads(unknown)["error"]["data"] == "method"
        assert stdout.getvalue().count("\n") == 1

    anyio.run(scenario)
