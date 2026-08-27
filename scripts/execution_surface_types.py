"""Shared immutable finding type for execution-surface scans."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, order=True)
class MutationSurface:
    """One exact structural mutation-authority finding."""

    path: str
    line: int
    kind: str
    name: str
