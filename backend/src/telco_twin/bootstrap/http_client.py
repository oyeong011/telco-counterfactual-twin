"""HTTPX2 client factory with the repository's production-safe defaults."""

from __future__ import annotations

import socket
from typing import TYPE_CHECKING, Final

import httpx2

if TYPE_CHECKING:
    from collections.abc import Mapping

LIMITS: Final = httpx2.Limits(
    max_connections=200,
    max_keepalive_connections=40,
    keepalive_expiry=30.0,
)
TIMEOUT: Final = httpx2.Timeout(connect=5.0, read=30.0, write=10.0, pool=10.0)
SOCKET_OPTIONS: Final[tuple[tuple[int, int, int], ...]] = (
    (socket.IPPROTO_TCP, socket.TCP_NODELAY, 1),
)


def create_http_client(
    base_url: str,
    headers: Mapping[str, str],
    transport: httpx2.BaseTransport | None = None,
) -> httpx2.Client:
    """Create a synchronous client with HTTP/2, retries, bounded pools, and split timeouts."""
    active_transport = transport or httpx2.HTTPTransport(
        http2=True,
        retries=3,
        limits=LIMITS,
        socket_options=SOCKET_OPTIONS,
    )
    return httpx2.Client(
        base_url=base_url,
        headers=headers,
        transport=active_transport,
        timeout=TIMEOUT,
        follow_redirects=True,
    )
