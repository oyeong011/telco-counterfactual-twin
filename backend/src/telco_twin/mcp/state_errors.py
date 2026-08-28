"""Typed MCP state errors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import override


@dataclass(frozen=True, slots=True)
class McpToolError(Exception):
    """Structured MCP tool failure."""

    code: str
    message: str

    @override
    def __str__(self) -> str:
        """Return a stable boundary string for logs and JSON-RPC errors."""
        return f"{self.code}: {self.message}"
