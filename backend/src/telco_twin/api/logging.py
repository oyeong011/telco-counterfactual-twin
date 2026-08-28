"""Minimal structured request logging with a secret-free field contract."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Final, override

from starlette.middleware.base import BaseHTTPMiddleware

from telco_twin.api.tracing import current_request_id

if TYPE_CHECKING:
    from fastapi import Request, Response
    from starlette.middleware.base import RequestResponseEndpoint

LOGGER: Final = logging.getLogger("telco_twin.api")
QUIET_PATHS: Final = frozenset({"/healthz", "/readyz"})


def log_response(method: str, path: str, status: int, request_id: str) -> None:
    """Record only joinable request metadata; headers and bodies are never accepted."""
    if path in QUIET_PATHS:
        return
    LOGGER.info(
        "api.request %s",
        json.dumps(
            {
                "method": method,
                "path": path,
                "request_id": request_id,
                "status": status,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
    )


class ResponseLoggingMiddleware(BaseHTTPMiddleware):
    """Log one sanitized boundary decision after each HTTP response."""

    @override
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Log the sanitized response decision after downstream handling."""
        response = await call_next(request)
        log_response(request.method, request.url.path, response.status_code, current_request_id())
        return response
