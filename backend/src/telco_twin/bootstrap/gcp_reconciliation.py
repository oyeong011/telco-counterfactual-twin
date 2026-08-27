"""Typed bounded polling policy for eventually consistent GCP reads."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from telco_twin.bootstrap import gcp_commands
from telco_twin.bootstrap.gcp_commands import ProvisioningError

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Callable

MINIMUM_WINDOW_SECONDS: Final = 90.0
DEFAULT_READ_TIMEOUT_SECONDS: Final = 15.0
DEFAULT_INITIAL_BACKOFF_SECONDS: Final = 0.25
DEFAULT_MAX_BACKOFF_SECONDS: Final = 8.0


@dataclass(frozen=True, slots=True)
class ReconciliationPolicy:
    """Bound total polling while injecting time for deterministic tests."""

    monotonic: Callable[[], float] = time.monotonic
    sleeper: Callable[[float], None] = time.sleep
    window_seconds: float = MINIMUM_WINDOW_SECONDS
    read_timeout_seconds: float = DEFAULT_READ_TIMEOUT_SECONDS
    initial_backoff_seconds: float = DEFAULT_INITIAL_BACKOFF_SECONDS
    max_backoff_seconds: float = DEFAULT_MAX_BACKOFF_SECONDS

    def __post_init__(self) -> None:
        """Reject policies that weaken the documented GCP visibility window."""
        if self.window_seconds < MINIMUM_WINDOW_SECONDS:
            code = "reconciliation-window-too-small"
            raise ProvisioningError(code)
        if (
            self.read_timeout_seconds <= 0
            or self.read_timeout_seconds > DEFAULT_READ_TIMEOUT_SECONDS
        ):
            code = "reconciliation-read-timeout-too-large"
            raise ProvisioningError(code)
        if self.initial_backoff_seconds <= 0 or self.max_backoff_seconds <= 0:
            code = "reconciliation-backoff-invalid"
            raise ProvisioningError(code)

    def read(self, arguments: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        """Run one reconciliation command under the per-read ceiling."""
        return gcp_commands.run_gcloud(
            arguments,
            timeout_seconds=self.read_timeout_seconds,
        )

    def poll[T](
        self,
        read: Callable[[], T],
        accept: Callable[[T], bool],
        *,
        confirmations: int = 1,
    ) -> T | None:
        """Poll with bounded backoff until an accepted state is observed."""
        if confirmations < 1:
            code = "reconciliation-confirmations-invalid"
            raise ProvisioningError(code)
        started = self.monotonic()
        scheduled_elapsed = 0.0
        delay = self.initial_backoff_seconds
        consecutive = 0
        while True:
            try:
                value = read()
            except ProvisioningError:
                consecutive = 0
            else:
                consecutive = consecutive + 1 if accept(value) else 0
                if consecutive >= confirmations:
                    return value
            elapsed = max(self.monotonic() - started, scheduled_elapsed)
            if elapsed >= self.window_seconds:
                return None
            remaining = self.window_seconds - elapsed
            wait = min(delay, self.max_backoff_seconds, remaining)
            self.sleeper(wait)
            scheduled_elapsed += wait
            delay = min(delay * 2, self.max_backoff_seconds)


DEFAULT_RECONCILIATION_POLICY: Final = ReconciliationPolicy()
