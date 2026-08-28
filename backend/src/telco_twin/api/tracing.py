"""Request-correlation context that never trusts client-supplied identifiers."""

from __future__ import annotations

import secrets
from contextvars import ContextVar, Token
from typing import TYPE_CHECKING, Final, override

from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from fastapi import Request, Response
    from starlette.middleware.base import RequestResponseEndpoint

REQUEST_ID: Final[ContextVar[str]] = ContextVar("twin_request_id", default="request-unknown")


def current_request_id() -> str:
    """Return the server-owned request correlation identifier."""
    return REQUEST_ID.get()


class RequestTracingMiddleware(BaseHTTPMiddleware):
    """Assign one server-owned request ID and expose it only as response metadata."""

    @override
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Create one correlation ID and attach it to the downstream response."""
        request_id = f"request-{secrets.token_hex(12)}"
        token: Token[str] = REQUEST_ID.set(request_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-Id"] = request_id
            return response
        finally:
            REQUEST_ID.reset(token)
