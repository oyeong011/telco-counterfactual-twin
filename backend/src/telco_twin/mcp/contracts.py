"""Stable MCP tool contracts for the non-authoritative twin interface."""

from __future__ import annotations

import hashlib
import json
from typing import Final, TypedDict

MCP_PROTOCOL_VERSION: Final = "2025-06-18"
TOOL_NAMES: Final = (
    "list_scenarios",
    "get_scenario",
    "diagnose_scenario",
    "propose_patch",
    "simulate_patch",
    "compare_runs",
    "request_approval",
)


class JsonSchema(TypedDict, total=False):
    """Small JSON Schema shape consumed by MCP clients."""

    type: str
    properties: dict[str, JsonSchema]
    required: list[str]
    additionalProperties: bool
    description: str


class ToolContract(TypedDict):
    """MCP tool declaration."""

    name: str
    description: str
    inputSchema: JsonSchema


class ToolManifest(TypedDict):
    """Versioned exported MCP manifest."""

    protocolVersion: str
    tools: list[ToolContract]


type JsonValue = str | int | bool | JsonMap | JsonList | None
type JsonMap = dict[str, JsonValue]
type JsonList = list[JsonValue]
type JsonRpc = dict[str, JsonValue]


EMPTY_OBJECT_SCHEMA: Final[JsonSchema] = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}


def _one_string_schema(field_name: str) -> JsonSchema:
    return {
        "type": "object",
        "properties": {field_name: {"type": "string"}},
        "required": [field_name],
        "additionalProperties": False,
    }


def _two_string_schema(first: str, second: str) -> JsonSchema:
    return {
        "type": "object",
        "properties": {first: {"type": "string"}, second: {"type": "string"}},
        "required": [first, second],
        "additionalProperties": False,
    }


def tool_manifest() -> ToolManifest:
    """Return the exact v0.1 MCP tool manifest."""
    return {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "tools": [
            {
                "name": "list_scenarios",
                "description": "List available synthetic scenarios and tool contracts.",
                "inputSchema": EMPTY_OBJECT_SCHEMA,
            },
            {
                "name": "get_scenario",
                "description": "Return one scenario manifest summary.",
                "inputSchema": _one_string_schema("scenario_id"),
            },
            {
                "name": "diagnose_scenario",
                "description": "Record deterministic fault evidence for one scenario.",
                "inputSchema": _one_string_schema("scenario_id"),
            },
            {
                "name": "propose_patch",
                "description": "Draft a bounded candidate patch for simulation.",
                "inputSchema": _two_string_schema("scenario_id", "target_id"),
            },
            {
                "name": "simulate_patch",
                "description": "Run baseline and candidate forks from immutable inputs.",
                "inputSchema": _two_string_schema("scenario_id", "patch_id"),
            },
            {
                "name": "compare_runs",
                "description": "Compare baseline and candidate evidence hashes.",
                "inputSchema": _one_string_schema("simulation_id"),
            },
            {
                "name": "request_approval",
                "description": "Record a draft approval request for external review.",
                "inputSchema": _two_string_schema("comparison_id", "simulation_id"),
            },
        ],
    }


def tool_manifest_hash() -> str:
    """Return the SHA-256 identity of the exported MCP manifest."""
    payload = json.dumps(tool_manifest(), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def tool_contracts_json() -> JsonList:
    """Return tool contracts as recursive JSON values for transport payloads."""
    tools: JsonList = []
    for tool in tool_manifest()["tools"]:
        tools.append(
            {
                "name": tool["name"],
                "description": tool["description"],
                "inputSchema": _schema_json(tool["inputSchema"]),
            }
        )
    return tools


def _schema_json(schema: JsonSchema) -> JsonMap:
    properties: JsonMap = {}
    for name, child in schema.get("properties", {}).items():
        properties[name] = _schema_json(child)
    result: JsonMap = {"type": schema.get("type", "object")}
    if properties:
        result["properties"] = properties
    if "required" in schema:
        result["required"] = list(schema["required"])
    if "additionalProperties" in schema:
        result["additionalProperties"] = schema["additionalProperties"]
    if "description" in schema:
        result["description"] = schema["description"]
    return result
