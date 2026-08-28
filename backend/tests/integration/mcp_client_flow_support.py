"""Official MCP client flow helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp.types import CallToolResult, TextContent

from .mcp_http_support import json_list, json_map, json_map_value, json_str

if TYPE_CHECKING:
    from mcp.client.session import ClientSession

    from telco_twin.mcp.contracts import JsonMap


async def full_evidence_flow(session: ClientSession) -> JsonMap:
    """Run diagnose→propose→simulate→compare→request through an MCP client."""
    listed = _tool_payload(await session.call_tool("list_scenarios", {}))
    scenarios = json_list(listed["scenarios"])
    scenario = json_map_value(scenarios[0])
    scenario_id = json_str(scenario["scenario_id"])
    manifest = _tool_payload(await session.call_tool("get_scenario", {"scenario_id": scenario_id}))
    diagnosis = _tool_payload(
        await session.call_tool("diagnose_scenario", {"scenario_id": scenario_id})
    )
    patch = _tool_payload(
        await session.call_tool(
            "propose_patch",
            {"scenario_id": scenario_id, "target_id": json_str(manifest["target_id"])},
        )
    )
    simulation = _tool_payload(
        await session.call_tool(
            "simulate_patch",
            {"scenario_id": scenario_id, "patch_id": json_str(patch["patch_id"])},
        )
    )
    comparison = _tool_payload(
        await session.call_tool(
            "compare_runs",
            {"simulation_id": json_str(simulation["simulation_id"])},
        )
    )
    approval = _tool_payload(
        await session.call_tool(
            "request_approval",
            {
                "comparison_id": json_str(comparison["comparison_id"]),
                "simulation_id": json_str(simulation["simulation_id"]),
            },
        )
    )
    assert diagnosis["effect"] == "diagnosis_evidence_recorded"
    return approval


def _tool_payload(result: CallToolResult) -> JsonMap:
    content = result.content[0]
    assert isinstance(content, TextContent)
    return json_map(content.text)
