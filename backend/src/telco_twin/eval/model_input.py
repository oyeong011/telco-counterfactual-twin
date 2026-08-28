"""Strict feature-only recorded-model input projection and opaque class codes."""

from __future__ import annotations

from enum import StrEnum, unique
from typing import TYPE_CHECKING, Annotated

from pydantic import Field

from telco_twin.domain._contract import StrictContract
from telco_twin.domain.scenario import FaultFamily
from telco_twin.simulator.network_model import AlarmKind

if TYPE_CHECKING:
    from telco_twin.eval.rules_baseline import DiagnosisCase


class ModelMetricFeatures(StrictContract):
    """Allowlisted numeric telemetry with all identifiers removed."""

    prb_utilization_pct: float
    sinr_db: float
    rsrp_dbm: float
    rsrq_db: float
    throughput_mbps: float
    latency_ms: float
    packet_loss_pct: float
    handover_attempts: int
    handover_failures: int
    active_ues: int
    slice_slo_throughput_mbps: float
    slice_throughput_mbps: float
    slice_slo_latency_ms: float
    slice_latency_ms: float
    nf_cpu_utilization_pct: float


class ModelConfigFeatures(StrictContract):
    """Allowlisted causal configuration values without target/version metadata."""

    neighbor_relation_valid: bool
    slice_scheduler_share_pct: float
    expected_slice_share_pct: float


@unique
class ModelFaultToken(StrEnum):
    """Case-independent semantic diagnosis vocabulary shown to the model."""

    AIR_INTERFACE_CAPACITY_PRESSURE = "air-interface-capacity-pressure"
    TRANSPORT_LINK_QUALITY_LOSS = "transport-link-quality-loss"
    PACKET_CORE_PROCESSING_PRESSURE = "packet-core-processing-pressure"
    MOBILITY_RELATION_CONFIGURATION = "mobility-relation-configuration"
    SLICE_RESOURCE_ALLOCATION = "slice-resource-allocation"
    UNTRUSTED_ALARM_INSTRUCTION = "untrusted-alarm-instruction"


class ModelInputView(StrictContract):
    """Only causal telemetry values allowed to reach the model prompt."""

    windows: tuple[ModelMetricFeatures, ...]
    configs: tuple[ModelConfigFeatures, ...]
    network_alarm_count: Annotated[int, Field(ge=0)]
    untrusted_instruction_alarm_count: Annotated[int, Field(ge=0)]


def fault_code(fault: FaultFamily) -> str:
    """Map an internal label to the case-independent semantic output token."""
    match fault:  # noqa: MATCH_OK - exhaustive enum
        case FaultFamily.RADIO_CONGESTION:
            return ModelFaultToken.AIR_INTERFACE_CAPACITY_PRESSURE
        case FaultFamily.BACKHAUL_DEGRADATION:
            return ModelFaultToken.TRANSPORT_LINK_QUALITY_LOSS
        case FaultFamily.UPF_SATURATION:
            return ModelFaultToken.PACKET_CORE_PROCESSING_PRESSURE
        case FaultFamily.NEIGHBOR_HANDOVER_MISCONFIGURATION:
            return ModelFaultToken.MOBILITY_RELATION_CONFIGURATION
        case FaultFamily.SLICE_SCHEDULER_MISALLOCATION:
            return ModelFaultToken.SLICE_RESOURCE_ALLOCATION
        case FaultFamily.ALARM_PROMPT_INJECTION:
            return ModelFaultToken.UNTRUSTED_ALARM_INSTRUCTION


def fault_from_code(raw: str) -> FaultFamily | None:
    """Parse one exact semantic model output token into an internal label."""
    try:
        token = ModelFaultToken(raw.strip().lower())
    except ValueError:
        return None
    match token:  # noqa: MATCH_OK - exhaustive vocabulary
        case ModelFaultToken.AIR_INTERFACE_CAPACITY_PRESSURE:
            label = FaultFamily.RADIO_CONGESTION
        case ModelFaultToken.TRANSPORT_LINK_QUALITY_LOSS:
            label = FaultFamily.BACKHAUL_DEGRADATION
        case ModelFaultToken.PACKET_CORE_PROCESSING_PRESSURE:
            label = FaultFamily.UPF_SATURATION
        case ModelFaultToken.MOBILITY_RELATION_CONFIGURATION:
            label = FaultFamily.NEIGHBOR_HANDOVER_MISCONFIGURATION
        case ModelFaultToken.SLICE_RESOURCE_ALLOCATION:
            label = FaultFamily.SLICE_SCHEDULER_MISALLOCATION
        case ModelFaultToken.UNTRUSTED_ALARM_INSTRUCTION:
            label = FaultFamily.ALARM_PROMPT_INJECTION
    return label


def build_model_input(case: DiagnosisCase) -> ModelInputView:
    """Project a frozen case through the strict feature allowlist."""
    network_alarms = 0
    instruction_alarms = 0
    for alarm in case.observation.alarms:
        match alarm.kind:  # noqa: MATCH_OK - exhaustive enum
            case AlarmKind.NETWORK_EVENT:
                network_alarms += 1
            case AlarmKind.PROMPT_INJECTION:
                instruction_alarms += 1
    return ModelInputView(
        windows=tuple(
            ModelMetricFeatures(
                prb_utilization_pct=window.prb_utilization_pct,
                sinr_db=window.sinr_db,
                rsrp_dbm=window.rsrp_dbm,
                rsrq_db=window.rsrq_db,
                throughput_mbps=window.throughput_mbps,
                latency_ms=window.latency_ms,
                packet_loss_pct=window.packet_loss_pct,
                handover_attempts=window.handover_attempts,
                handover_failures=window.handover_failures,
                active_ues=window.active_ues,
                slice_slo_throughput_mbps=window.slice_slo_throughput_mbps,
                slice_throughput_mbps=window.slice_throughput_mbps,
                slice_slo_latency_ms=window.slice_slo_latency_ms,
                slice_latency_ms=window.slice_latency_ms,
                nf_cpu_utilization_pct=window.nf_cpu_utilization_pct,
            )
            for window in case.observation.windows
        ),
        configs=tuple(
            ModelConfigFeatures(
                neighbor_relation_valid=config.neighbor_relation_valid,
                slice_scheduler_share_pct=config.slice_scheduler_share_pct,
                expected_slice_share_pct=config.expected_slice_share_pct,
            )
            for config in case.observation.config_history
        ),
        network_alarm_count=network_alarms,
        untrusted_instruction_alarm_count=instruction_alarms,
    )


def recorded_model_prompts(cases: tuple[DiagnosisCase, ...]) -> tuple[str, ...]:
    """Build fixed label-free zero-shot prompts from only allowlisted features."""
    vocabulary = ",".join(token.value for token in ModelFaultToken)
    instruction = f"Return exactly one semantic class token from [{vocabulary}]."
    evidence_rule = "Use only the allowlisted numeric and boolean telemetry."
    return tuple(
        f"{instruction} {evidence_rule} Input: " + build_model_input(case).model_dump_json()
        for case in cases
    )
