"""Official MCP Streamable HTTP client QA against a live ASGI server."""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

import anyio
import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from .mcp_client_flow_support import full_evidence_flow


def test_real_mcp_streamable_http_client_completes_full_evidence_flow() -> None:
    port = _free_port()
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "telco_twin.mcp.http_app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=Path.cwd(),
    )

    async def scenario() -> None:
        try:
            _wait_for_port(port)
            http_client = httpx2.AsyncClient(headers={"Origin": "https://portfolio.example"})
            async with (
                http_client,
                streamable_http_client(f"http://127.0.0.1:{port}/mcp", http_client=http_client) as (
                    read_stream,
                    write_stream,
                ),
                ClientSession(read_stream, write_stream) as session,
            ):
                initialized = await session.initialize()
                tools = await session.list_tools()
                approval = await full_evidence_flow(session)
        finally:
            process.terminate()
            _ = process.wait(timeout=10)

        assert initialized.server_info.name == "telco-counterfactual-twin"
        assert tools.tools[0].name == "list_scenarios"
        assert approval["network_change_permitted"] is False

    anyio.run(scenario)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_port(port: int) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return
        except OSError:
            time.sleep(0.05)
    message = f"uvicorn did not listen on {port}"
    raise TimeoutError(message)
