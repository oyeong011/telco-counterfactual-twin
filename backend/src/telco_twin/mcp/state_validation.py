"""Validation and identity helpers for MCP evidence state."""

from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING, Final

from telco_twin.mcp.contracts import tool_manifest
from telco_twin.mcp.state_errors import McpToolError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from telco_twin.mcp.contracts import JsonValue

ID_RE: Final = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")


def validate_arguments(name: str, arguments: Mapping[str, JsonValue]) -> None:
    """Validate tool arguments against the exported input schema."""
    tools = {tool["name"]: tool["inputSchema"] for tool in tool_manifest()["tools"]}
    schema = tools.get(name)
    if schema is None:
        return
    allowed = set(schema.get("properties", {}))
    required = set(schema.get("required", []))
    present = set(arguments)
    if not required.issubset(present) or present - allowed:
        code = "bad_arguments"
        raise tool_error(code, "arguments do not match the tool schema")
    if any(not isinstance(arguments[field], str) for field in present):
        code = "bad_arguments"
        raise tool_error(code, "arguments must be strings")


def required_id(arguments: Mapping[str, JsonValue], key: str) -> str:
    """Return a schema-valid identifier argument."""
    value = arguments.get(key)
    if value is None:
        code = "missing_argument"
        raise tool_error(code, f"{key} is required")
    if not isinstance(value, str):
        code = "bad_arguments"
        raise tool_error(code, f"{key} must be a string")
    if ID_RE.fullmatch(value) is None:
        code = "malformed_identifier"
        raise tool_error(code, f"{key} has invalid format")
    return value


def stable_id(prefix: str, *parts: str) -> str:
    """Return a stable prefixed SHA-256 identifier."""
    digest = hashlib.sha256("\0".join(parts).encode()).hexdigest()
    return f"{prefix}-{digest}"


def tool_error(code: str, message: str) -> McpToolError:
    """Build a typed tool error."""
    return McpToolError(code, message)
