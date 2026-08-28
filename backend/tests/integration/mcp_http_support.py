"""Shared fixtures for Streamable HTTP MCP integration tests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter

from telco_twin.mcp.asgi import McpAsgiApp
from telco_twin.mcp.contracts import (
    MCP_PROTOCOL_VERSION,
    JsonList,
    JsonMap,
    JsonValue,
)

if TYPE_CHECKING:
    from telco_twin.mcp.http_boundary import ReceiveMessage, SendMessage
    from telco_twin.mcp.session_store import McpSession

type Headers = list[tuple[bytes, bytes]]
JSON_MAP_ADAPTER: Final[TypeAdapter[JsonMap]] = TypeAdapter(dict[str, JsonValue])
JSON_LIST_ADAPTER: Final[TypeAdapter[JsonList]] = TypeAdapter(list[JsonValue])
HEADERS_ADAPTER: Final[TypeAdapter[Headers]] = TypeAdapter(list[tuple[bytes, bytes]])


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
    body: JsonMap | None = None,
    raw_body: bytes | None = None,
    path: str = "/mcp",
) -> AsgiResponse:
    """Call the ASGI app once with an optional JSON body."""
    sent: list[SendMessage] = []
    payload = (
        raw_body if raw_body is not None else b"" if body is None else json.dumps(body).encode()
    )

    async def receive() -> ReceiveMessage:
        return {"type": "http.request", "body": payload, "more_body": False}

    async def send(message: SendMessage) -> None:
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
    sent: list[SendMessage] = []
    messages: list[ReceiveMessage] = [
        {"type": "http.request", "body": chunk, "more_body": index < len(chunks) - 1}
        for index, chunk in enumerate(chunks)
    ]
    message_iter = iter(messages)

    async def receive() -> ReceiveMessage:
        return next(message_iter)

    async def send(message: SendMessage) -> None:
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


def initialize_body() -> JsonMap:
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


def json_map(payload: bytes | str) -> JsonMap:
    """Parse one JSON object response without erasing recursive value types."""
    return JSON_MAP_ADAPTER.validate_json(payload)


def json_map_value(value: JsonValue) -> JsonMap:
    """Narrow one recursive JSON value to an object."""
    return JSON_MAP_ADAPTER.validate_python(value)


def json_list(value: JsonValue) -> JsonList:
    """Narrow one recursive JSON value to an array."""
    return JSON_LIST_ADAPTER.validate_python(value)


def json_str(value: JsonValue) -> str:
    """Narrow one recursive JSON value to a string."""
    assert isinstance(value, str)
    return value


def live_session(app: McpAsgiApp, session_id: str) -> McpSession:
    """Return one live public session observable."""
    session = app.session(session_id)
    assert session is not None
    return session


def append_pings(session: McpSession, stream_id: str, count: int) -> list[str]:
    """Append legitimate server pings and return their event IDs."""
    event_ids: list[str] = []
    for _ in range(count):
        frame = session.append_ping(stream_id)
        assert frame is not None
        event_ids.append(frame[0])
    return event_ids


def retained_ids(session: McpSession, stream_id: str) -> list[str]:
    """Return retained event IDs for one observable stream."""
    return [event.event_id for event in session.streams[stream_id].events]


def _response(sent: list[SendMessage]) -> AsgiResponse:
    start = sent[0]
    status = start["status"]
    assert isinstance(status, int)
    raw_headers = dict(HEADERS_ADAPTER.validate_python(start["headers"]))
    body = sent[-1].get("body", b"")
    assert isinstance(body, bytes)
    return AsgiResponse(
        status=status,
        headers={key.decode().lower(): value.decode() for key, value in raw_headers.items()},
        body=body,
    )
