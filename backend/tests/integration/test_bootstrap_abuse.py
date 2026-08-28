"""Adversarial bounds for public bootstrap abuse state."""
# pyright: reportPrivateUsage=false

from datetime import UTC, datetime

import anyio
from fastapi.testclient import TestClient

from telco_twin.api.abuse import BootstrapRateLimiter
from telco_twin.api.app import create_app
from telco_twin.state.trusted_clock import FixedClock

from .api_test_support import ALLOWED_ORIGIN


def test_per_ip_limiter_retains_at_most_4096_client_buckets() -> None:
    async def scenario() -> None:
        # Given: more unique client identities than the limiter may retain.
        limiter = BootstrapRateLimiter(FixedClock(datetime(2026, 8, 28, tzinfo=UTC)))
        for index in range(4097):
            _ = await limiter.consume(f"synthetic-client-{index:04d}")
        # When/Then: attacker-controlled cardinality remains bounded.
        assert len(limiter._buckets) == 4096

    anyio.run(scenario)


def test_bootstrap_rejects_streaming_body_without_content_length_before_buffering() -> None:
    # Given: an unauthenticated chunked request with no declared byte length.
    with TestClient(create_app()) as client:
        # When: its streaming body reaches the bootstrap boundary.
        response = client.post(
            "/api/demo-sessions",
            headers={"Origin": ALLOWED_ORIGIN, "Content-Type": "application/json"},
            content=iter((b"{" + (b"x" * 5000), b"x" * 5000 + b"}")),
        )
    # Then: the server rejects missing length rather than buffering arbitrary chunks.
    assert response.status_code == 411
    assert response.json()["code"] == "content_length_required"
