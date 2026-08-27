"""Typed provider-probe failures that never include credential material."""

from __future__ import annotations

from dataclasses import dataclass
from typing import override


@dataclass(frozen=True, slots=True)
class ProviderProbeError(Exception):
    """A stable provider failure code safe for redacted reports."""

    code: str

    @override
    def __str__(self) -> str:
        """Return the stable redacted code."""
        return self.code
