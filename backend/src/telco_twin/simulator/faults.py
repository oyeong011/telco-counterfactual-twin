"""Closed six-family diagnosis over typed observations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
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
SLICE_THROUGHPUT_RATIO_THRESHOLD: Final = 0.7
SLICE_SCHEDULER_SHARE_RATIO_THRESHOLD: Final = 0.5
# Fault-onset thresholds are inclusive. SLO equality is healthy only for the latency ceiling.


@unique
class DiagnosisStatus(StrEnum):
    """Closed diagnosis outcome that distinguishes nominal from ambiguity."""

    NO_FAULT = "no-fault"
    PRIMARY = "primary"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class FaultDiagnosis:
    """One primary fault, or explicit secondary evidence when ambiguous."""

    status: DiagnosisStatus
    primary_fault: FaultFamily | None
    secondary_evidence: tuple[FaultFamily, ...]


def diagnose_fault(observation: NetworkObservation) -> FaultDiagnosis:
    """Evaluate every family independently in deterministic enum order."""
    windows = tuple(
        sorted(observation.windows, key=lambda item: (item.observed_at, item.target_id))
    )
    candidates = tuple(
        family
        for family, detected in (
            (
                FaultFamily.RADIO_CONGESTION,
                any(_is_radio_congestion(window) for window in windows),
            ),
            (
                FaultFamily.BACKHAUL_DEGRADATION,
                any(_is_backhaul_degradation(window) for window in windows),
            ),
            (
                FaultFamily.UPF_SATURATION,
                any(_is_upf_saturation(window) for window in windows),
            ),
            (
                FaultFamily.NEIGHBOR_HANDOVER_MISCONFIGURATION,
                any(
                    _is_handover_misconfiguration(
                        window,
                        _latest_causal_config(window, observation.config_history),
                    )
                    for window in windows
                ),
            ),
            (
                FaultFamily.SLICE_SCHEDULER_MISALLOCATION,
                any(
                    _is_slice_misallocation(
                        window,
                        _latest_causal_config(window, observation.config_history),
                    )
                    for window in windows
                ),
            ),
            (
                FaultFamily.ALARM_PROMPT_INJECTION,
                any(
                    _is_causal_alarm(alarm, windows) and _is_prompt_injection(alarm)
                    for alarm in observation.alarms
                ),
            ),
        )
        if detected
    )
    if not candidates:
        return FaultDiagnosis(
            status=DiagnosisStatus.NO_FAULT,
            primary_fault=None,
            secondary_evidence=(),
        )
    if len(candidates) == 1:
        return FaultDiagnosis(
            status=DiagnosisStatus.PRIMARY,
            primary_fault=candidates[0],
            secondary_evidence=(),
        )
    return FaultDiagnosis(
        status=DiagnosisStatus.AMBIGUOUS,
        primary_fault=None,
        secondary_evidence=candidates,
    )


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
    )


def _is_upf_saturation(window: MetricWindow) -> bool:
    return (
        window.nf_cpu_utilization_pct >= UPF_CPU_THRESHOLD_PCT
        and window.latency_ms >= UPF_LATENCY_THRESHOLD_MS
    )


def _is_handover_misconfiguration(
    window: MetricWindow,
    config: ConfigSnapshot | None,
) -> bool:
    return (
        config is not None
        and window.handover_attempts >= HANDOVER_ATTEMPT_THRESHOLD
        and (
            window.handover_failures / window.handover_attempts >= HANDOVER_FAILURE_RATIO_THRESHOLD
        )
        and not config.neighbor_relation_valid
    )


def _is_slice_misallocation(window: MetricWindow, config: ConfigSnapshot | None) -> bool:
    return (
        config is not None
        and window.slice_throughput_mbps
        <= SLICE_THROUGHPUT_RATIO_THRESHOLD * window.slice_slo_throughput_mbps
        and window.slice_latency_ms > window.slice_slo_latency_ms
        and config.slice_scheduler_share_pct
        <= SLICE_SCHEDULER_SHARE_RATIO_THRESHOLD * config.expected_slice_share_pct
    )


def _latest_causal_config(
    window: MetricWindow,
    configs: tuple[ConfigSnapshot, ...],
) -> ConfigSnapshot | None:
    causal = tuple(
        config
        for config in configs
        if config.target_id == window.target_id and config.recorded_at <= window.observed_at
    )
    return max(causal, key=lambda item: (item.recorded_at, item.config_version), default=None)


def _is_causal_alarm(alarm: AlarmEvidence, windows: tuple[MetricWindow, ...]) -> bool:
    return any(
        window.target_id == alarm.target_id and alarm.observed_at <= window.observed_at
        for window in windows
    )


def _is_prompt_injection(alarm: AlarmEvidence) -> bool:
    match alarm.kind:
        case AlarmKind.NETWORK_EVENT:
            return False
        case AlarmKind.PROMPT_INJECTION:
            return True
        case _:
            assert_never(alarm.kind)
