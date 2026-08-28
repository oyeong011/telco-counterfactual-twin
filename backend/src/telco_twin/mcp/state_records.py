"""Typed bounded evidence records for MCP tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from telco_twin.mcp.state_errors import McpToolError

if TYPE_CHECKING:
    from collections.abc import Sized

    from telco_twin.counterfactual.runner import CounterfactualRun


@dataclass(frozen=True, slots=True)
class SimulationDraft:
    """Recorded counterfactual simulation draft."""

    scenario_id: str
    patch_id: str
    run: CounterfactualRun
    simulation_id: str


@dataclass(frozen=True, slots=True)
class DiagnosisRecord:
    """Append-only evidence record for one diagnosis request."""

    diagnosis_id: str
    scenario_id: str
    target_id: str
    manifest_hash: str


@dataclass(frozen=True, slots=True)
class ApprovalRequestRecord:
    """Append-only non-authoritative approval draft record."""

    approval_request_id: str
    comparison_id: str
    simulation_id: str
    network_change_permitted: bool


def ensure_room(items: Sized, max_records: int) -> None:
    """Fail before appending when a bounded evidence map is full."""
    if len(items) >= max_records:
        code = "record_cap_exceeded"
        raise McpToolError(code, "evidence record cap exceeded")
