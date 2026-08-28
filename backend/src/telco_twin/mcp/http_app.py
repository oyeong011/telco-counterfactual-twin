"""ASGI entrypoint for the local MCP Streamable HTTP service."""

from __future__ import annotations

from telco_twin.mcp.asgi import McpAsgiApp

app = McpAsgiApp(allowed_origins=frozenset({"https://portfolio.example"}))
