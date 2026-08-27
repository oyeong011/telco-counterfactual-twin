"""Versioned deterministic fault-scenario contract."""

from __future__ import annotations

from enum import StrEnum, unique
from typing import Annotated

from pydantic import Field

from ._contract import ContractId, RootContract, SafeProperties, Seed, UtcTimestamp


@unique
class FaultFamily(StrEnum):
    """The exact six synthetic fault families in the accepted product scope."""

    RADIO_CONGESTION = "radio-congestion"
    BACKHAUL_DEGRADATION = "backhaul-degradation"
    UPF_SATURATION = "upf-saturation"
    NEIGHBOR_HANDOVER_MISCONFIGURATION = "neighbor-handover-misconfiguration"
    SLICE_SCHEDULER_MISALLOCATION = "slice-scheduler-misallocation"
    ALARM_PROMPT_INJECTION = "alarm-prompt-injection"


class Scenario(RootContract):
    """Seeded, bounded input manifest for one synthetic fault."""

    scenario_id: ContractId
    topology_id: ContractId
    seed: Seed
    fault_family: FaultFamily
    starts_at: UtcTimestamp
    duration_seconds: Annotated[int, Field(ge=1, le=3600)]
    target_ids: Annotated[tuple[ContractId, ...], Field(min_length=1, max_length=16)]
    parameters: SafeProperties
