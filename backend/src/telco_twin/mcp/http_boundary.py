"""Typed HTTP boundary helpers for the Streamable HTTP adapter."""

from __future__ import annotations

import json
from typing import Protocol, TypedDict, TypeGuard

from pydantic import TypeAdapter, ValidationError

from telco_twin.mcp.contracts import JsonRpc, JsonValue
from telco_twin.mcp.state import McpToolError

type HeaderList = list[tuple[bytes, bytes]]
type ReceiveMessage = dict[str, str | bytes | bool]
type SendMessage = dict[str, str | int | HeaderList | bytes]
type RequestId = str | int | None
JSON_RPC_ADAPTER: TypeAdapter[JsonRpc] = TypeAdapter(dict[str, JsonValue])


class Scope(TypedDict):
    """HTTP subset of ASGI scope consumed by this app."""

    type: str
    method: str
    path: str
    headers: HeaderList


class LifespanScope(TypedDict):
    """Lifespan subset of ASGI scope consumed by this app."""

    type: str


class Receive(Protocol):
    """ASGI receive callable."""

    async def __call__(self) -> ReceiveMessage:
        """Return one ASGI receive message."""
        ...


class Send(Protocol):
    """ASGI send callable."""

    async def __call__(self, message: SendMessage) -> None:
        """Send one ASGI message."""
        ...


class JsonRequest(TypedDict, total=False):
    """Parsed JSON-RPC request fields used by this adapter."""

    jsonrpc: str
    id: RequestId
    method: str
    params: JsonValue


def headers(raw_headers: HeaderList) -> dict[str, str]:
    """Decode ASGI headers into a lower-case mapping."""
    return {key.decode().lower(): value.decode() for key, value in raw_headers}


def is_http_scope(scope: Scope | LifespanScope) -> TypeGuard[Scope]:
    """Return whether the ASGI scope has the HTTP fields this adapter consumes."""
    return scope["type"] == "http"


def accepts(headers_map: dict[str, str], *required_media_types: str) -> bool:
    """Return whether Accept contains every required media type exactly."""
    offered = _media_ranges(headers_map.get("accept", ""))
    return all(required in offered for required in required_media_types)


def has_json_content_type(headers_map: dict[str, str]) -> bool:
    """Return whether Content-Type is exactly application/json, ignoring parameters."""
    content_type = headers_map.get("content-type", "")
    return _single_media_type(content_type) == "application/json"


async def read_body(receive: Receive, max_body_bytes: int) -> bytes:
    """Aggregate a possibly chunked ASGI request body with a hard byte cap."""
    chunks: list[bytes] = []
    total = 0
    more_body = True
    while more_body:
        message = await receive()
        chunk = message.get("body", b"")
        if isinstance(chunk, bytes):
            total += len(chunk)
            if total > max_body_bytes:
                code = "body_too_large"
                raise McpToolError(code, "request body is too large")
            chunks.append(chunk)
        more_body = message.get("more_body") is True
    return b"".join(chunks)


def parse_request(payload: bytes) -> JsonRequest:
    """Parse a JSON-RPC object payload."""
    try:
        parsed = JSON_RPC_ADAPTER.validate_json(payload)
    except ValidationError as exc:
        error_type = exc.errors()[0].get("type")
        code = "bad_json" if error_type == "json_invalid" else "bad_json_rpc"
        raise McpToolError(code, "invalid JSON") from exc
    except UnicodeDecodeError as exc:
        code = "bad_json"
        raise McpToolError(code, "invalid JSON") from exc
    if parsed.get("jsonrpc") != "2.0":
        code = "bad_json_rpc"
        raise McpToolError(code, "invalid JSON-RPC request")
    request = JsonRequest(jsonrpc="2.0")
    if "id" in parsed:
        request["id"] = _parse_id(parsed["id"])
    parsed_method = parsed.get("method")
    if isinstance(parsed_method, str):
        request["method"] = parsed_method
    if "params" in parsed:
        request["params"] = parsed["params"]
    return request


def _parse_id(value: JsonValue) -> RequestId:
    match value:
        case str():
            return value
        case int() if not isinstance(value, bool):
            return value
        case _:
            code = "bad_json_rpc"
            raise McpToolError(code, "id must be string or integer")


def error(request_id: RequestId, code: int, reason: str, message: str) -> JsonRpc:
    """Build a JSON-RPC error payload."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message, "data": reason},
    }


async def send_json(
    send: Send,
    status: int,
    payload: dict[str, JsonValue],
    extra_headers: HeaderList,
) -> None:
    """Send one compact JSON response."""
    body = json.dumps(payload, separators=(",", ":")).encode()
    headers_out = [(b"content-type", b"application/json"), *extra_headers]
    await send_response(send, status, headers_out, body)


async def send_response(send: Send, status: int, headers_out: HeaderList, body: bytes) -> None:
    """Send one complete ASGI HTTP response."""
    await send({"type": "http.response.start", "status": status, "headers": headers_out})
    await send({"type": "http.response.body", "body": body})


def sse_body(events: list[tuple[str, JsonRpc]]) -> bytes:
    """Serialize JSON-RPC events to SSE frames."""
    chunks = [
        f"id: {event_id}\nevent: message\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"
        for event_id, payload in events
    ]
    return "".join(chunks).encode()


def _media_ranges(header_value: str) -> frozenset[str]:
    values = {
        _single_media_type(part)
        for part in header_value.split(",")
        if _single_media_type(part) != ""
    }
    return frozenset(values)


def _single_media_type(value: str) -> str:
    return value.split(";", maxsplit=1)[0].strip().lower()
