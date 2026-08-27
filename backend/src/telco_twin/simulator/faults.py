"""Closed six-family diagnosis over typed observations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, assert_never

from telco_twin.domain.scenario import FaultFamily
from telco_twin.simulator.network_model import AlarmKind

if TYPE_CHECKING:
    from telco_twin.simulator.metrics import MetricWindow
    from telco_twin.simulator.network_model import (
        AlarmEvidence,
        ConfigSnapshot,
        NetworkObservation,
    )

RADIO_PRB_THRESHOLD_PCT: Final = 90.0
RADIO_ACTIVE_UE_THRESHOLD: Final = 300
RADIO_THROUGHPUT_THRESHOLD_MBPS: Final = 400.0
BACKHAUL_LOSS_THRESHOLD_PCT: Final = 5.0
BACKHAUL_LATENCY_THRESHOLD_MS: Final = 100.0
UPF_CPU_THRESHOLD_PCT: Final = 90.0
UPF_LATENCY_THRESHOLD_MS: Final = 75.0
HANDOVER_ATTEMPT_THRESHOLD: Final = 20
HANDOVER_FAILURE_RATIO_THRESHOLD: Final = 0.25
SLICE_TRANSPORT_LOSS_CEILING_PCT: Final = 2.0


@dataclass(frozen=True, slots=True)
class FaultDiagnosis:
    """One primary fault, or explicit secondary evidence when ambiguous."""

    primary_fault: FaultFamily | None
    secondary_evidence: tuple[FaultFamily, ...]


def diagnose_fault(observation: NetworkObservation) -> FaultDiagnosis:
    """Diagnose from typed metrics and alarm kind, never from alarm prose."""
    window = max(observation.windows, key=lambda item: item.observed_at)
    config = max(observation.config_history, key=lambda item: item.recorded_at)
    candidates = tuple(
        family
        for family, detected in (
            (FaultFamily.RADIO_CONGESTION, _is_radio_congestion(window)),
            (FaultFamily.BACKHAUL_DEGRADATION, _is_backhaul_degradation(window)),
            (FaultFamily.UPF_SATURATION, _is_upf_saturation(window)),
            (
                FaultFamily.NEIGHBOR_HANDOVER_MISCONFIGURATION,
                _is_handover_misconfiguration(window, config),
            ),
            (
                FaultFamily.SLICE_SCHEDULER_MISALLOCATION,
                _is_slice_misallocation(window, config),
            ),
            (
                FaultFamily.ALARM_PROMPT_INJECTION,
                any(_is_prompt_injection(alarm) for alarm in observation.alarms),
            ),
        )
        if detected
    )
    if len(candidates) == 1:
        return FaultDiagnosis(primary_fault=candidates[0], secondary_evidence=())
    return FaultDiagnosis(primary_fault=None, secondary_evidence=candidates)


def _is_radio_congestion(window: MetricWindow) -> bool:
    return (
        window.prb_utilization_pct >= RADIO_PRB_THRESHOLD_PCT
        and window.active_ues >= RADIO_ACTIVE_UE_THRESHOLD
        and window.throughput_mbps <= RADIO_THROUGHPUT_THRESHOLD_MBPS
    )


def _is_backhaul_degradation(window: MetricWindow) -> bool:
    return (
        window.packet_loss_pct >= BACKHAUL_LOSS_THRESHOLD_PCT
        and window.latency_ms >= BACKHAUL_LATENCY_THRESHOLD_MS
        and window.nf_cpu_utilization_pct < UPF_CPU_THRESHOLD_PCT
    )


def _is_upf_saturation(window: MetricWindow) -> bool:
    return (
        window.nf_cpu_utilization_pct >= UPF_CPU_THRESHOLD_PCT
        and window.latency_ms >= UPF_LATENCY_THRESHOLD_MS
        and window.packet_loss_pct < BACKHAUL_LOSS_THRESHOLD_PCT
    )


def _is_handover_misconfiguration(window: MetricWindow, config: ConfigSnapshot) -> bool:
    return (
        window.handover_attempts >= HANDOVER_ATTEMPT_THRESHOLD
        and (
            window.handover_failures / window.handover_attempts >= HANDOVER_FAILURE_RATIO_THRESHOLD
        )
        and not config.neighbor_relation_valid
    )


def _is_slice_misallocation(window: MetricWindow, config: ConfigSnapshot) -> bool:
    return (
        window.slice_throughput_mbps < 0.7 * window.slice_slo_throughput_mbps
        and window.slice_latency_ms > window.slice_slo_latency_ms
        and config.slice_scheduler_share_pct < 0.5 * config.expected_slice_share_pct
        and window.packet_loss_pct < SLICE_TRANSPORT_LOSS_CEILING_PCT
        and window.nf_cpu_utilization_pct < UPF_CPU_THRESHOLD_PCT
    )


def _is_prompt_injection(alarm: AlarmEvidence) -> bool:
    match alarm.kind:
        case AlarmKind.NETWORK_EVENT:
            return False
        case AlarmKind.PROMPT_INJECTION:
            return True
        case _:
            assert_never(alarm.kind)
