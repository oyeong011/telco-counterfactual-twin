"""Integration tests for MCP evidence-state tools."""

import anyio
import pytest

from telco_twin.data.synthetic import generate_manifest
from telco_twin.mcp.contracts import TOOL_NAMES, JsonValue
from telco_twin.mcp.state import EvidenceMcpService, McpToolError


def test_happy_path_records_counterfactual_evidence_without_approval() -> None:
    async def scenario() -> None:
        # Given: a fresh evidence-only MCP service.
        service = EvidenceMcpService()
        # When: an agent completes the diagnose/propose/simulate/compare/request flow.
        listed = await service.call_tool("list_scenarios", {})
        assert "scenarios" in listed
        scenario_id = listed["scenarios"][0]["scenario_id"]
        diagnosis = await service.call_tool("diagnose_scenario", {"scenario_id": scenario_id})
        assert "target_id" in diagnosis
        proposal = await service.call_tool(
            "propose_patch",
            {"scenario_id": scenario_id, "target_id": diagnosis["target_id"]},
        )
        assert "patch_id" in proposal
        simulation = await service.call_tool(
            "simulate_patch",
            {"scenario_id": scenario_id, "patch_id": proposal["patch_id"]},
        )
        assert "simulation_id" in simulation
        comparison = await service.call_tool(
            "compare_runs",
            {"simulation_id": simulation["simulation_id"]},
        )
        assert "comparison_id" in comparison
        service._comparisons["comparison-other"] = "simulation-other"
        approval = await service.call_tool(
            "request_approval",
            {
                "comparison_id": comparison["comparison_id"],
                "simulation_id": simulation["simulation_id"],
            },
        )
        # Then: the state contains draft evidence, not execution authority.
        assert "tools" in listed
        assert "status" in approval
        assert "effect" in approval
        assert "network_change_permitted" in approval
        assert tuple(tool["name"] for tool in listed["tools"]) == TOOL_NAMES
        assert approval["status"] == "draft"
        assert approval["effect"] == "approval_request_recorded"
        assert approval["network_change_permitted"] is False
        assert service.review_draft_only is True

    anyio.run(scenario)


def test_request_approval_rejects_missing_simulation_and_injection() -> None:
    async def scenario() -> None:
        # Given: a fresh evidence-only MCP service.
        service = EvidenceMcpService()
        # When/Then: missing simulations and prompt-injection shaped IDs fail closed.
        for payload in (
            {"comparison_id": "comparison-missing", "simulation_id": "simulation-missing"},
            {"comparison_id": "comparison-0001; execute", "simulation_id": "simulation-0001"},
        ):
            with pytest.raises(McpToolError) as caught:
                _ = await service.call_tool("request_approval", payload)
            assert caught.value.code in {"missing_simulation", "malformed_identifier"}

    anyio.run(scenario)


def test_diagnosis_and_approval_effects_are_backed_by_bounded_records() -> None:
    async def scenario() -> None:
        service = EvidenceMcpService(max_records=1)
        listed = await service.call_tool("list_scenarios", {})
        assert "scenarios" in listed
        scenario_id = listed["scenarios"][0]["scenario_id"]
        scenario = await service.call_tool("get_scenario", {"scenario_id": scenario_id})
        assert "target_id" in scenario
        diagnosis = await service.call_tool("diagnose_scenario", {"scenario_id": scenario_id})
        proposal = await service.call_tool(
            "propose_patch",
            {"scenario_id": scenario_id, "target_id": scenario["target_id"]},
        )
        assert "patch_id" in proposal
        simulation = await service.call_tool(
            "simulate_patch",
            {"scenario_id": scenario_id, "patch_id": proposal["patch_id"]},
        )
        assert "simulation_id" in simulation
        comparison = await service.call_tool(
            "compare_runs",
            {"simulation_id": simulation["simulation_id"]},
        )
        assert "comparison_id" in comparison
        approval = await service.call_tool(
            "request_approval",
            {
                "comparison_id": comparison["comparison_id"],
                "simulation_id": simulation["simulation_id"],
            },
        )

        assert "effect" in diagnosis
        assert "diagnosis_id" in diagnosis
        assert "effect" in approval
        assert diagnosis["effect"] == "diagnosis_evidence_recorded"
        assert service.diagnosis_records()[0].diagnosis_id == diagnosis["diagnosis_id"]
        assert approval["effect"] == "approval_request_recorded"
        assert service.approval_request_records()[0].comparison_id == comparison["comparison_id"]
        other = generate_manifest(54)
        service._scenarios[other.scenario.scenario_id] = other
        with pytest.raises(McpToolError) as caught:
            _ = await service.call_tool(
                "diagnose_scenario",
                {"scenario_id": other.scenario.scenario_id},
            )
        assert caught.value.code == "record_cap_exceeded"

    anyio.run(scenario)


def test_tool_state_rejects_schema_and_missing_state_edges() -> None:
    async def scenario() -> None:
        service = EvidenceMcpService()
        listed = await service.call_tool("list_scenarios", {})
        assert "scenarios" in listed
        scenario_id = listed["scenarios"][0]["scenario_id"]
        scenario = await service.call_tool("get_scenario", {"scenario_id": scenario_id})
        assert "target_id" in scenario
        proposal = await service.call_tool(
            "propose_patch",
            {"scenario_id": scenario_id, "target_id": scenario["target_id"]},
        )
        assert "patch_id" in proposal
        simulation = await service.call_tool(
            "simulate_patch",
            {"scenario_id": scenario_id, "patch_id": proposal["patch_id"]},
        )
        assert "simulation_id" in simulation
        comparison = await service.call_tool(
            "compare_runs",
            {"simulation_id": simulation["simulation_id"]},
        )
        assert "comparison_id" in comparison
        service._comparisons["comparison-other"] = "simulation-other"

        cases: list[tuple[str, dict[str, JsonValue], str]] = [
            ("list_scenarios", {"unexpected": "x"}, "bad_arguments"),
            ("get_scenario", {}, "bad_arguments"),
            ("get_scenario", {"scenario_id": 1}, "bad_arguments"),
            ("get_scenario", {"scenario_id": "missing-scenario"}, "unknown_scenario"),
            (
                "propose_patch",
                {"scenario_id": scenario_id, "target_id": "missing-target"},
                "unknown_target",
            ),
            (
                "simulate_patch",
                {"scenario_id": scenario_id, "patch_id": "missing-patch"},
                "unknown_patch",
            ),
            ("compare_runs", {"simulation_id": "missing-simulation"}, "missing_simulation"),
            (
                "request_approval",
                {
                    "comparison_id": "missing-comparison",
                    "simulation_id": simulation["simulation_id"],
                },
                "missing_comparison",
            ),
            (
                "request_approval",
                {
                    "comparison_id": comparison["comparison_id"],
                    "simulation_id": "missing-simulation",
                },
                "missing_simulation",
            ),
            (
                "request_approval",
                {
                    "comparison_id": "comparison-other",
                    "simulation_id": simulation["simulation_id"],
                },
                "missing_simulation",
            ),
        ]
        for name, arguments, code in cases:
            with pytest.raises(McpToolError) as caught:
                _ = await service.call_tool(name, arguments)
            assert caught.value.code == code

    anyio.run(scenario)
