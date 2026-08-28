"""Bounded bootstrap body and per-IP token-bucket controls."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, final, override

import anyio
from starlette.middleware.base import BaseHTTPMiddleware

from telco_twin.api.errors import ProblemError, problem_response
from telco_twin.state.trusted_clock import TrustedClock, trusted_now

if TYPE_CHECKING:
    from datetime import datetime

    from fastapi import Request, Response
    from starlette.middleware.base import RequestResponseEndpoint

BOOTSTRAP_PATH: Final = "/api/demo-sessions"
BOOTSTRAP_BODY_LIMIT: Final = 8 * 1024
BOOTSTRAP_BURST: Final = 10.0
BOOTSTRAP_REFILL_PER_SECOND: Final = 5.0 / 60.0
MAX_BOOTSTRAP_CLIENT_BUCKETS: Final = 4096


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    """One token-bucket admission result and bounded retry delay."""

    accepted: bool
    retry_after_seconds: int


@final
class _Bucket:
    """Mutable token bucket protected exclusively by the limiter lock."""

    __slots__ = ("observed_at", "tokens")
    observed_at: datetime
    tokens: float

    def __init__(self, tokens: float, observed_at: datetime) -> None:
        self.tokens = tokens
        self.observed_at = observed_at


@final
class BootstrapRateLimiter:
    """Per-client-IP five-per-minute limiter with an exact burst of ten."""

    def __init__(self, clock: TrustedClock) -> None:
        """Bind the limiter to application-owned trusted time."""
        self._clock = clock
        self._lock = anyio.Lock()
        self._buckets: dict[str, _Bucket] = {}

    async def consume(self, client_ip: str) -> RateLimitResult:
        """Consume one token using trusted monotonic wall instants."""
        now = trusted_now(self._clock)
        async with self._lock:
            bucket = self._buckets.get(client_ip)
            if bucket is None:
                if len(self._buckets) >= MAX_BOOTSTRAP_CLIENT_BUCKETS:
                    oldest_ip = min(
                        self._buckets,
                        key=lambda candidate: (
                            self._buckets[candidate].observed_at,
                            candidate,
                        ),
                    )
                    del self._buckets[oldest_ip]
                bucket = _Bucket(BOOTSTRAP_BURST, now)
                self._buckets[client_ip] = bucket
            elapsed = max(0.0, (now - bucket.observed_at).total_seconds())
            bucket.tokens = min(
                BOOTSTRAP_BURST,
                bucket.tokens + (elapsed * BOOTSTRAP_REFILL_PER_SECOND),
            )
            bucket.observed_at = max(bucket.observed_at, now)
            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return RateLimitResult(accepted=True, retry_after_seconds=0)
            retry = max(1, math.ceil((1.0 - bucket.tokens) / BOOTSTRAP_REFILL_PER_SECOND))
            return RateLimitResult(accepted=False, retry_after_seconds=retry)


class BootstrapBodyLimitMiddleware(BaseHTTPMiddleware):
    """Reject oversized bootstrap bodies before FastAPI body parsing."""

    @override
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Reject an oversized body and otherwise preserve the request stream."""
        if request.method != "POST" or request.url.path != BOOTSTRAP_PATH:
            return await call_next(request)
        content_length = request.headers.get("content-length")
        if content_length is None:
            return problem_response(
                ProblemError(
                    411,
                    "content_length_required",
                    "Content length required",
                    "Bootstrap requires a declared Content-Length no greater than 8 KiB.",
                )
            )
        try:
            declared = int(content_length)
        except ValueError:
            return problem_response(
                ProblemError(
                    400,
                    "content_length_invalid",
                    "Invalid content length",
                    "The content length is invalid.",
                )
            )
        if declared > BOOTSTRAP_BODY_LIMIT:
            return problem_response(
                ProblemError(
                    413,
                    "bootstrap_body_too_large",
                    "Bootstrap body too large",
                    "The bootstrap body exceeds 8 KiB.",
                )
            )
        body = await request.body()
        if len(body) > BOOTSTRAP_BODY_LIMIT:
            return problem_response(
                ProblemError(
                    413,
                    "bootstrap_body_too_large",
                    "Bootstrap body too large",
                    "The bootstrap body exceeds 8 KiB.",
                )
            )
        return await call_next(request)
