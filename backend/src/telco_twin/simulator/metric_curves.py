"""Per-family response curves: how each observable channel moves with fault intensity.

Each family drives a few channels linearly from their nominal value toward a
peak reached at intensity 1.0. The peaks are chosen so the family's rule
threshold is crossed strictly inside the range, which is what makes near-miss
and just-past-onset cases possible at all. The onset intensities below are
derived from the same numbers the rules use, so the two can never drift apart
silently.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from telco_twin.domain.scenario import FaultFamily
from telco_twin.simulator.faults import (
    HANDOVER_FAILURE_RATIO_THRESHOLD,
    RADIO_PRB_THRESHOLD_PCT,
    RADIO_THROUGHPUT_THRESHOLD_MBPS,
    UPF_CPU_THRESHOLD_PCT,
)

NOMINAL_WINDOW: Final[dict[str, float | int]] = {
    "prb_utilization_pct": 55.0,
    "sinr_db": 18.0,
    "rsrp_dbm": -85.0,
    "rsrq_db": -10.0,
    "throughput_mbps": 800.0,
    "latency_ms": 20.0,
    "packet_loss_pct": 0.1,
    "handover_attempts": 100,
    "handover_failures": 2,
    "active_ues": 120,
    "slice_slo_throughput_mbps": 200.0,
    "slice_throughput_mbps": 240.0,
    "slice_slo_latency_ms": 50.0,
    "slice_latency_ms": 25.0,
    "nf_cpu_utilization_pct": 45.0,
}
NOMINAL_SLICE_SHARE_PCT: Final = 40.0


@dataclass(frozen=True, slots=True)
class Curve:
    """One family's response.

    Channels the family drives, the peak each reaches at intensity 1.0, and the
    one channel a masked case pins at nominal so the rules cannot conclude.
    """

    window_peaks: dict[str, float]
    config_peaks: dict[str, float]
    onset: float
    masked_channel: str


def _linear(nominal: float, peak: float, intensity: float) -> float:
    return nominal + (peak - nominal) * intensity


def _onset_radio() -> float:
    prb = (RADIO_PRB_THRESHOLD_PCT - 55.0) / (100.0 - 55.0)
    ues = (300 - 120) / (400 - 120)
    throughput = (800.0 - RADIO_THROUGHPUT_THRESHOLD_MBPS) / (800.0 - 250.0)
    return max(prb, ues, throughput)


def _onset_handover() -> float:
    # ratio(i) = (2 + 128 i) / (100 + 100 i) >= r  ->  i >= (100 r - 2) / (128 - 100 r)
    r = HANDOVER_FAILURE_RATIO_THRESHOLD
    return (100 * r - 2) / (128 - 100 * r)


CURVES: Final[dict[FaultFamily, Curve]] = {
    FaultFamily.RADIO_CONGESTION: Curve(
        window_peaks={"prb_utilization_pct": 100.0, "active_ues": 400, "throughput_mbps": 250.0},
        config_peaks={},
        onset=_onset_radio(),
        masked_channel="throughput_mbps",
    ),
    FaultFamily.BACKHAUL_DEGRADATION: Curve(
        window_peaks={"packet_loss_pct": 14.0, "latency_ms": 240.0},
        config_peaks={},
        onset=max((5.0 - 0.1) / (14.0 - 0.1), (100.0 - 20.0) / (240.0 - 20.0)),
        masked_channel="latency_ms",
    ),
    FaultFamily.UPF_SATURATION: Curve(
        window_peaks={"nf_cpu_utilization_pct": 100.0, "latency_ms": 170.0},
        config_peaks={},
        onset=max((UPF_CPU_THRESHOLD_PCT - 45.0) / (100.0 - 45.0), (75.0 - 20.0) / (170.0 - 20.0)),
        masked_channel="latency_ms",
    ),
    FaultFamily.NEIGHBOR_HANDOVER_MISCONFIGURATION: Curve(
        window_peaks={"handover_attempts": 200, "handover_failures": 130},
        config_peaks={"neighbor_relation_valid": 0.0},
        onset=_onset_handover(),
        masked_channel="neighbor_relation_valid",
    ),
    FaultFamily.SLICE_SCHEDULER_MISALLOCATION: Curve(
        window_peaks={"slice_throughput_mbps": 30.0, "slice_latency_ms": 150.0},
        config_peaks={"slice_scheduler_share_pct": 4.0},
        onset=max(
            (240.0 - 140.0) / (240.0 - 30.0),
            (25.0 - 50.0) / (25.0 - 150.0),
            (40.0 - 20.0) / (40.0 - 4.0),
        ),
        masked_channel="slice_scheduler_share_pct",
    ),
}


def apply_curve(
    family: FaultFamily,
    intensity: float,
    window: dict[str, float | int],
    config: dict[str, float | bool],
    *,
    masked: bool,
) -> None:
    """Move one family's channels toward their peaks in place."""
    curve = CURVES[family]
    for channel, peak in curve.window_peaks.items():
        if masked and channel == curve.masked_channel:
            continue
        current = window[channel]
        value = _linear(float(current), peak, intensity)
        window[channel] = round(value) if isinstance(current, int) else value
    for channel, peak in curve.config_peaks.items():
        if masked and channel == curve.masked_channel:
            continue
        if channel == "neighbor_relation_valid":
            config[channel] = not intensity > 0.0
        else:
            config[channel] = _linear(NOMINAL_SLICE_SHARE_PCT, peak, intensity)
