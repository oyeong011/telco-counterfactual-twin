"""TypedDict result shapes for MCP evidence tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from telco_twin.mcp.contracts import ToolContract


class JsonObject(TypedDict, total=False):
    """Tool result object serializable to JSON."""

    status: str
    effect: str
    network_change_permitted: bool
    tools: list[ToolContract]
    scenarios: list[dict[str, str | int]]
    scenario_id: str
    topology_hash: str
    manifest_hash: str
    target_id: str
    diagnosis_id: str
    patch_id: str
    patch_hash: str
    simulation_id: str
    comparison_id: str
    approval_request_id: str
    approval_eligible: bool
