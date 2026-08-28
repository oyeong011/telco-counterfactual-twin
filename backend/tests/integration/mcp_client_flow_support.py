"""Official MCP client flow helpers."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from mcp.types import CallToolResult, TextContent

if TYPE_CHECKING:
    from mcp.client.session import ClientSession


async def full_evidence_flow(session: ClientSession) -> dict[str, object]:
    """Run diagnose→propose→simulate→compare→request through an MCP client."""
    listed = _tool_payload(await session.call_tool("list_scenarios", {}))
    scenarios = listed["scenarios"]
    assert isinstance(scenarios, list)
    scenario = scenarios[0]
    assert isinstance(scenario, dict)
    scenario_id = str(scenario["scenario_id"])
    manifest = _tool_payload(await session.call_tool("get_scenario", {"scenario_id": scenario_id}))
    diagnosis = _tool_payload(
        await session.call_tool("diagnose_scenario", {"scenario_id": scenario_id})
    )
    patch = _tool_payload(
        await session.call_tool(
            "propose_patch",
            {"scenario_id": scenario_id, "target_id": str(manifest["target_id"])},
        )
    )
    simulation = _tool_payload(
        await session.call_tool(
            "simulate_patch",
            {"scenario_id": scenario_id, "patch_id": str(patch["patch_id"])},
        )
    )
    comparison = _tool_payload(
        await session.call_tool("compare_runs", {"simulation_id": str(simulation["simulation_id"])})
    )
    approval = _tool_payload(
        await session.call_tool(
            "request_approval",
            {
                "comparison_id": str(comparison["comparison_id"]),
                "simulation_id": str(simulation["simulation_id"]),
            },
        )
    )
    assert diagnosis["effect"] == "diagnosis_evidence_recorded"
    return approval


def _tool_payload(result: CallToolResult) -> dict[str, object]:
    content = result.content[0]
    assert isinstance(content, TextContent)
    parsed = json.loads(content.text)
    assert isinstance(parsed, dict)
    return parsed
