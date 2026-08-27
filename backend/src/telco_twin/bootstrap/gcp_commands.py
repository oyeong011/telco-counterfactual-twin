"""Secret-safe gcloud command boundary for reversible preflight probes."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, override

if TYPE_CHECKING:
    from pathlib import Path

DEFAULT_COMMAND_TIMEOUT_SECONDS: Final = 15.0
COMMAND_TIMEOUT_RETURN_CODE: Final = 124
COMMAND_OS_ERROR_RETURN_CODE: Final = 126


@dataclass(frozen=True, slots=True)
class GcpContext:
    """Non-secret identifiers needed by the GCP preflight."""

    project_id: str
    project_number: str
    billing_account_id: str
    owner_id: str


@dataclass(frozen=True, slots=True)
class ProvisioningError(Exception):
    """Stable failure code that never embeds provider stderr."""

    code: str

    @override
    def __str__(self) -> str:
        """Return the stable redacted failure code."""
        return self.code


def run_command(
    arguments: tuple[str, ...],
    *,
    timeout_seconds: float | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run an argv-only provider command while keeping output captured."""
    active_timeout = DEFAULT_COMMAND_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
    try:
        return subprocess.run(
            arguments,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=active_timeout,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            arguments,
            COMMAND_TIMEOUT_RETURN_CODE,
            "",
            "",
        )
    except OSError:
        return subprocess.CompletedProcess(
            arguments,
            COMMAND_OS_ERROR_RETURN_CODE,
            "",
            "",
        )


def run_gcloud(
    arguments: tuple[str, ...],
    *,
    timeout_seconds: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one gcloud command through the secret-safe command boundary."""
    return run_command(arguments, timeout_seconds=timeout_seconds)


def require_gcloud(arguments: tuple[str, ...], code: str) -> str:
    """Return captured stdout or raise a stable redacted failure."""
    result = run_gcloud(arguments)
    if result.returncode != 0:
        raise ProvisioningError(code)
    return result.stdout.strip()


def attempt_gcloud(arguments: tuple[str, ...]) -> bool:
    """Return only whether a cleanup command succeeded."""
    return run_gcloud(arguments).returncode == 0
