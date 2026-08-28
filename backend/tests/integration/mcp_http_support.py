"""Shared fixtures for Streamable HTTP MCP integration tests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from telco_twin.mcp.asgi import McpAsgiApp
from telco_twin.mcp.contracts import MCP_PROTOCOL_VERSION

if TYPE_CHECKING:
    from telco_twin.mcp.http_boundary import ReceiveMessage

type Headers = list[tuple[bytes, bytes]]


@dataclass(frozen=True, slots=True)
class AsgiResponse:
    """Captured single-response ASGI exchange."""

    status: int
    headers: dict[str, str]
    body: bytes


async def request(  # noqa: PLR0913
    app: McpAsgiApp,
    *,
    method: str,
    headers: Headers,
    body: dict[str, Any] | None = None,
    raw_body: bytes | None = None,
    path: str = "/mcp",
) -> AsgiResponse:
    """Call the ASGI app once with an optional JSON body."""
    sent: list[dict[str, Any]] = []
    payload = (
        raw_body if raw_body is not None else b"" if body is None else json.dumps(body).encode()
    )

    async def receive() -> ReceiveMessage:
        return {"type": "http.request", "body": payload, "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await app({"type": "http", "method": method, "path": path, "headers": headers}, receive, send)
    return _response(sent)


async def chunked_request(
    app: McpAsgiApp,
    *,
    method: str,
    headers: Headers,
    chunks: list[bytes],
) -> AsgiResponse:
    """Call the ASGI app once with chunked body frames."""
    sent: list[dict[str, Any]] = []
    messages: list[ReceiveMessage] = [
        {"type": "http.request", "body": chunk, "more_body": index < len(chunks) - 1}
        for index, chunk in enumerate(chunks)
    ]
    message_iter = iter(messages)

    async def receive() -> ReceiveMessage:
        return next(message_iter)

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await app(
        {"type": "http", "method": method, "path": "/mcp", "headers": headers},
        receive,
        send,
    )
    return _response(sent)


def post_headers(session_id: str | None = None) -> Headers:
    """Return strict POST headers for the portfolio origin."""
    headers = [
        (b"origin", b"https://portfolio.example"),
        (b"accept", b"application/json, text/event-stream"),
        (b"content-type", b"application/json; charset=utf-8"),
    ]
    if session_id is not None:
        headers.extend(
            [
                (b"mcp-session-id", session_id.encode()),
                (b"mcp-protocol-version", MCP_PROTOCOL_VERSION.encode()),
            ]
        )
    return headers


def sse_headers(session_id: str, last_event_id: str | None = None) -> Headers:
    """Return strict GET SSE headers for the portfolio origin."""
    headers = [
        (b"origin", b"https://portfolio.example"),
        (b"accept", b"text/event-stream"),
        (b"mcp-session-id", session_id.encode()),
        (b"mcp-protocol-version", MCP_PROTOCOL_VERSION.encode()),
    ]
    if last_event_id is not None:
        headers.append((b"last-event-id", last_event_id.encode()))
    return headers


async def initialized_app() -> tuple[McpAsgiApp, str]:
    """Create and activate one MCP HTTP session."""
    app = McpAsgiApp(allowed_origins=frozenset({"https://portfolio.example"}))
    created = await request(app, method="POST", headers=post_headers(), body=initialize_body())
    session_id = created.headers["mcp-session-id"]
    activated = await request(
        app,
        method="POST",
        headers=post_headers(session_id),
        body={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    assert created.status == 200
    assert activated.status == 202
    return app, session_id


def initialize_body() -> dict[str, Any]:
    """Return a supported initialize request."""
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "0"},
        },
    }


def sse_ids(body: bytes) -> list[str]:
    """Return event IDs from an SSE payload."""
    return [
        line.removeprefix("id: ") for line in body.decode().splitlines() if line.startswith("id: ")
    ]


def stream_token(body: bytes) -> str:
    """Return the session+stream token from the first SSE ID."""
    event_id = sse_ids(body)[0]
    return ":".join(event_id.split(":")[:2])


def _response(sent: list[dict[str, Any]]) -> AsgiResponse:
    start = sent[0]
    raw_headers = dict(start["headers"])
    return AsgiResponse(
        status=int(start["status"]),
        headers={key.decode().lower(): value.decode() for key, value in raw_headers.items()},
        body=sent[-1].get("body", b""),
    )
