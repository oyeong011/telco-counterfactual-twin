"""Typed metric windows and fail-closed observation-quality boundaries."""

from __future__ import annotations

from enum import StrEnum, unique
from typing import Annotated, Self

from pydantic import Field, model_validator, validate_call

from telco_twin.domain._contract import (
    ContractId,
    StrictContract,
    UtcTimestamp,
    utc_datetime,
)
from telco_twin.domain._validation import fail_validation

type Percent = Annotated[float, Field(ge=0, le=100)]
type NonnegativeMetric = Annotated[float, Field(ge=0, le=1_000_000)]
type PositiveMetric = Annotated[float, Field(gt=0, le=1_000_000)]


@unique
class ObservationQualityFlag(StrEnum):
    """Machine-readable reasons an observation cannot support approval."""

    STALE = "stale-window"
    NOISY = "noisy-window"


class MetricWindow(StrictContract):
    """One complete telecom observation window; missing values are never imputed."""

    target_id: ContractId
    observed_at: UtcTimestamp
    prb_utilization_pct: Percent
    sinr_db: Annotated[float, Field(ge=-30, le=50)]
    rsrp_dbm: Annotated[float, Field(ge=-160, le=-40)]
    rsrq_db: Annotated[float, Field(ge=-30, le=0)]
    throughput_mbps: NonnegativeMetric
    latency_ms: Annotated[float, Field(ge=0, le=60_000)]
    packet_loss_pct: Percent
    handover_attempts: Annotated[int, Field(ge=0, le=1_000_000)]
    handover_failures: Annotated[int, Field(ge=0, le=1_000_000)]
    active_ues: Annotated[int, Field(ge=0, le=1_000_000)]
    slice_slo_throughput_mbps: PositiveMetric
    slice_throughput_mbps: NonnegativeMetric
    slice_slo_latency_ms: Annotated[float, Field(gt=0, le=60_000)]
    slice_latency_ms: Annotated[float, Field(ge=0, le=60_000)]
    nf_cpu_utilization_pct: Percent

    @model_validator(mode="after")
    def failures_do_not_exceed_attempts(self) -> Self:
        """Keep handover counts physically ordered."""
        if self.handover_failures > self.handover_attempts:
            fail_validation("handover_count_order", "handover failures exceed attempts")
        return self


class QualityPolicy(StrictContract):
    """Bounded deterministic thresholds for observation quality."""

    max_age_seconds: Annotated[int, Field(ge=1, le=3600)] = 120
    max_prb_spread_pct: Annotated[float, Field(gt=0, le=100)] = 25.0
    max_sinr_spread_db: Annotated[float, Field(gt=0, le=80)] = 8.0
    max_latency_spread_ms: Annotated[float, Field(gt=0, le=60_000)] = 50.0


class QualityContext(StrictContract):
    """Assessment instant and thresholds, independent of wall clock."""

    assessed_at: UtcTimestamp
    policy: QualityPolicy = Field(default_factory=QualityPolicy)


class QualityAssessment(StrictContract):
    """Typed quality flags and their fail-closed eligibility consequence."""

    flags: tuple[ObservationQualityFlag, ...]
    approval_eligible: bool

    @model_validator(mode="after")
    def eligibility_matches_flags(self) -> Self:
        """Make any quality flag fail closed."""
        if self.approval_eligible is bool(self.flags):
            fail_validation("quality_eligibility", "quality flags and eligibility disagree")
        return self


@validate_call
def assess_observation_quality(
    windows: Annotated[tuple[MetricWindow, ...], Field(min_length=1, max_length=128)],
    context: QualityContext,
) -> QualityAssessment:
    """Assess freshness and bounded noise without filling missing data."""
    assessed_at = utc_datetime(context.assessed_at)
    ages = tuple(
        (assessed_at - utc_datetime(window.observed_at)).total_seconds() for window in windows
    )
    stale = any(age < 0 or age > context.policy.max_age_seconds for age in ages)
    prb_values = tuple(window.prb_utilization_pct for window in windows)
    sinr_values = tuple(window.sinr_db for window in windows)
    latency_values = tuple(window.latency_ms for window in windows)
    noisy = (
        max(prb_values) - min(prb_values) > context.policy.max_prb_spread_pct
        or max(sinr_values) - min(sinr_values) > context.policy.max_sinr_spread_db
        or max(latency_values) - min(latency_values) > context.policy.max_latency_spread_ms
    )
    flags: list[ObservationQualityFlag] = []
    if stale:
        flags.append(ObservationQualityFlag.STALE)
    if noisy:
        flags.append(ObservationQualityFlag.NOISY)
    frozen_flags = tuple(flags)
    return QualityAssessment(flags=frozen_flags, approval_eligible=not frozen_flags)
