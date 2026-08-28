"""Streamable HTTP ASGI adapter for the evidence-only MCP surface."""

from __future__ import annotations

from dataclasses import dataclass, field

from telco_twin.mcp.contracts import (
    MCP_PROTOCOL_VERSION,
    JsonRpc,
    tool_contracts_json,
)
from telco_twin.mcp.http_boundary import (
    JsonRequest,
    LifespanScope,
    Receive,
    Scope,
    Send,
    accepts,
    error,
    has_json_content_type,
    headers,
    is_http_scope,
    parse_request,
    read_body,
    send_json,
    send_response,
    sse_body,
)
from telco_twin.mcp.http_tools import tool_result
from telco_twin.mcp.session_store import McpSession, McpSessionStore
from telco_twin.mcp.state import EvidenceMcpService, McpToolError

SUPPORTED_HANDSHAKE_VERSIONS = frozenset(
    {"2024-11-05", "2025-03-26", MCP_PROTOCOL_VERSION, "2025-11-25"}
)
SERVER_INFO: JsonRpc = {"name": "telco-counterfactual-twin", "version": "0.1.0"}


@dataclass(slots=True)
class McpAsgiApp:  # noqa: D101
    allowed_origins: frozenset[str]
    ttl_seconds: int = 900
    max_body_bytes: int = 65_536
    max_sessions: int = 50
    max_stream_events: int = 256
    max_retained_streams: int = 8
    max_session_replay_events: int = 256
    service: EvidenceMcpService = field(default_factory=EvidenceMcpService)
    _store: McpSessionStore = field(init=False)

    def __post_init__(self) -> None:  # noqa: D105
        self._store = McpSessionStore(
            ttl_seconds=self.ttl_seconds,
            max_sessions=self.max_sessions,
            max_stream_events=self.max_stream_events,
            max_retained_streams=self.max_retained_streams,
            max_session_replay_events=self.max_session_replay_events,
        )

    @property
    def _sessions(self) -> dict[str, McpSession]:
        return self._store.sessions

    async def __call__(  # noqa: D102
        self, scope: Scope | LifespanScope, receive: Receive, send: Send
    ) -> None:
        match scope["type"]:
            case "lifespan":
                await self._lifespan(receive, send)
            case "http":
                if is_http_scope(scope):
                    await self._handle_http(scope, receive, send)
            case _:
                await send_response(send, 500, [], b"")

    async def _lifespan(self, receive: Receive, send: Send) -> None:
        while True:
            message = await receive()
            match message.get("type"):
                case "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                case "lifespan.shutdown":
                    self._store.clear()
                    await send({"type": "lifespan.shutdown.complete"})
                    return
                case _:
                    self._store.clear()
                    await send({"type": "lifespan.shutdown.complete"})
                    return

    async def _handle_http(self, scope: Scope, receive: Receive, send: Send) -> None:
        headers_map = headers(scope["headers"])
        if scope["path"] != "/mcp":
            await send_json(send, 404, error(None, -32004, "not_found", "path not found"), [])
            return
        if headers_map.get("origin") not in self.allowed_origins:
            await send_json(send, 403, error(None, -32003, "forbidden", "origin rejected"), [])
            return
        match scope["method"]:
            case "POST":
                await self._post(headers_map, receive, send)
            case "GET":
                await self._get(headers_map, send)
            case "DELETE":
                await self._delete(headers_map, send)
            case _:
                await send_json(send, 405, error(None, -32005, "method", "method rejected"), [])

    async def _post(self, headers_map: dict[str, str], receive: Receive, send: Send) -> None:
        if not accepts(headers_map, "application/json", "text/event-stream"):
            await send_json(send, 400, error(None, -32000, "accept", "dual accept required"), [])
            return
        if not has_json_content_type(headers_map):
            await send_json(send, 400, error(None, -32000, "content_type", "JSON required"), [])
            return
        try:
            request = parse_request(await read_body(receive, self.max_body_bytes))
        except McpToolError as exc:
            status = 413 if exc.code == "body_too_large" else 400
            await send_json(send, status, error(None, -32600, exc.code, exc.message), [])
            return
        if request.get("method") == "initialize":
            await self._initialize(request, headers_map.get("mcp-session-id"), send)
            return
        session = self._store.require(headers_map, MCP_PROTOCOL_VERSION)
        match session:
            case int() as status:
                await send_json(
                    send,
                    status,
                    error(request.get("id"), -32001, "session", "bad session"),
                    [],
                )
            case McpSession():
                await self._dispatch(session, request, send)

    async def _initialize(
        self,
        request: JsonRequest,
        session_id: str | None,
        send: Send,
    ) -> None:
        if "id" not in request:
            await send_json(send, 400, error(None, -32600, "bad_json_rpc", "id is required"), [])
            return
        if session_id is not None:
            await send_json(
                send,
                400,
                error(request.get("id"), -32001, "session", "already set"),
                [],
            )
            return
        params = request.get("params", {})
        if (
            not isinstance(params, dict)
            or params.get("protocolVersion") not in SUPPORTED_HANDSHAKE_VERSIONS
        ):
            await send_json(
                send,
                400,
                error(request.get("id"), -32002, "version", "unsupported"),
                [],
            )
            return
        if not isinstance(params.get("capabilities"), dict) or not isinstance(
            params.get("clientInfo"), dict
        ):
            await send_json(
                send,
                400,
                error(request.get("id"), -32602, "bad_params", "initialize params are required"),
                [],
            )
            return
        try:
            session = self._store.create()
        except McpToolError as exc:
            await send_json(send, 429, error(request.get("id"), -32029, exc.code, exc.message), [])
            return
        response: JsonRpc = {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "result": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "serverInfo": SERVER_INFO,
                "capabilities": {"tools": {}},
            },
        }
        await send_json(send, 200, response, [(b"mcp-session-id", session.session_id.encode())])

    async def _dispatch(self, session: McpSession, request: JsonRequest, send: Send) -> None:
        method = request.get("method")
        if not isinstance(method, str):
            await send_response(send, 202, [], b"")
            return
        if "id" not in request:
            if method == "notifications/initialized":
                session.initialized = True
            await send_response(send, 202, [], b"")
            return
        if not session.initialized:
            await send_json(
                send,
                400,
                error(request.get("id"), -32002, "not_initialized", "initialize is incomplete"),
                [],
            )
            return
        match method:
            case "tools/list":
                payload: JsonRpc = {"tools": tool_contracts_json()}
            case "tools/call":
                try:
                    payload = await tool_result(self.service, request)
                except McpToolError as exc:
                    await send_json(
                        send,
                        400,
                        error(request.get("id"), -32010, exc.code, exc.message),
                        [],
                    )
                    return
            case _:
                await send_json(
                    send,
                    400,
                    error(request.get("id"), -32601, "method", "unknown"),
                    [],
                )
                return
        await send_json(send, 200, {"jsonrpc": "2.0", "id": request["id"], "result": payload}, [])

    async def _get(self, headers_map: dict[str, str], send: Send) -> None:
        if not accepts(headers_map, "text/event-stream"):
            await send_json(send, 400, error(None, -32000, "accept", "SSE accept required"), [])
            return
        session = self._store.require(headers_map, MCP_PROTOCOL_VERSION)
        match session:
            case int() as status:
                await send_json(send, status, error(None, -32001, "session", "bad session"), [])
            case McpSession():
                last = headers_map.get("last-event-id")
                events: list[tuple[str, JsonRpc]] | None = (
                    session.open_stream() if last is None or last == "0" else session.replay(last)
                )
                if events is None:
                    await send_json(send, 404, error(None, -32001, "session", "bad session"), [])
                    return
                await send_response(
                    send,
                    200,
                    [(b"content-type", b"text/event-stream")],
                    sse_body(events),
                )

    async def _delete(self, headers_map: dict[str, str], send: Send) -> None:
        session_id = headers_map.get("mcp-session-id")
        session = self._store.require(headers_map, MCP_PROTOCOL_VERSION)
        match session:
            case int() as status:
                await send_json(send, status, error(None, -32001, "session", "bad session"), [])
            case McpSession():
                if session_id is not None:
                    _ = self._store.delete(session_id)
                await send_response(send, 204, [], b"")
