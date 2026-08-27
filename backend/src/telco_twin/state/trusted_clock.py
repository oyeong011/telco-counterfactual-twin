"""Trusted UTC clock contract shared by local safety state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, final, override


class TrustedClock(Protocol):
    """Application-owned time provider unavailable to request bodies."""

    def now(self) -> datetime:
        """Return the current timezone-aware instant."""
        ...


@dataclass(frozen=True, slots=True)
class TrustedClockError(Exception):
    """A configured clock returned a timezone-naive instant."""

    @override
    def __str__(self) -> str:
        return "trusted-clock-time-invalid"


def trusted_now(clock: TrustedClock) -> datetime:
    """Return one normalized UTC instant or fail closed."""
    current = clock.now()
    if current.tzinfo is None or current.utcoffset() is None:
        raise TrustedClockError
    return current.astimezone(UTC)


def trusted_timestamp(clock: TrustedClock) -> str:
    """Return trusted time at whole-second RFC3339 precision."""
    return trusted_now(clock).strftime("%Y-%m-%dT%H:%M:%SZ")


@final
class SystemClock:
    """Production wall-clock provider."""

    def now(self) -> datetime:
        """Return current UTC wall time."""
        return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class FixedClock:
    """Immutable deterministic provider for local/CI evidence flows."""

    current: datetime

    def now(self) -> datetime:
        """Return the configured instant."""
        return self.current
