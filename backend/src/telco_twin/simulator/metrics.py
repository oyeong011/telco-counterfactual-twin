"""Typed metric windows and fail-closed observation-quality boundaries."""

from __future__ import annotations

from enum import StrEnum, unique
from typing import TYPE_CHECKING, Annotated, Protocol, Self

from pydantic import Field, model_validator

from telco_twin.domain._contract import (
    ContractId,
    StrictContract,
    UtcTimestamp,
    utc_datetime,
)
from telco_twin.domain._validation import fail_validation

if TYPE_CHECKING:
    from collections.abc import Sequence

type Percent = Annotated[float, Field(strict=True, ge=0, le=100)]
type NonnegativeMetric = Annotated[float, Field(strict=True, ge=0, le=1_000_000)]
type PositiveMetric = Annotated[float, Field(strict=True, gt=0, le=1_000_000)]


class ObservedEvidence(Protocol):
    """Quality-visible evidence carrying an observation timestamp."""

    @property
    def observed_at(self) -> str:
        """Return the validated UTC observation timestamp."""
        ...


class RecordedEvidence(Protocol):
    """Quality-visible configuration carrying a record timestamp."""

    @property
    def recorded_at(self) -> str:
        """Return the validated UTC configuration timestamp."""
        ...


class QualityObservation(Protocol):
    """Structural evidence bundle consumed by the quality gate."""

    @property
    def windows(self) -> Sequence[MetricWindow]:
        """Return complete metric windows."""
        ...

    @property
    def alarms(self) -> Sequence[ObservedEvidence]:
        """Return typed alarm evidence."""
        ...

    @property
    def config_history(self) -> Sequence[RecordedEvidence]:
        """Return typed configuration evidence."""
        ...


@unique
class ObservationQualityFlag(StrEnum):
    """Machine-readable reasons an observation cannot support approval."""

    STALE = "stale-window"
    FUTURE = "future-evidence"
    NOISY = "noisy-window"


class MetricWindow(StrictContract):
    """One complete telecom observation window; missing values are never imputed."""

    target_id: ContractId
    observed_at: UtcTimestamp
    prb_utilization_pct: Percent
    sinr_db: Annotated[float, Field(strict=True, ge=-30, le=50)]
    rsrp_dbm: Annotated[float, Field(strict=True, ge=-160, le=-40)]
    rsrq_db: Annotated[float, Field(strict=True, ge=-30, le=0)]
    throughput_mbps: NonnegativeMetric
    latency_ms: Annotated[float, Field(strict=True, ge=0, le=60_000)]
    packet_loss_pct: Percent
    handover_attempts: Annotated[int, Field(strict=True, ge=0, le=1_000_000)]
    handover_failures: Annotated[int, Field(strict=True, ge=0, le=1_000_000)]
    active_ues: Annotated[int, Field(strict=True, ge=0, le=1_000_000)]
    slice_slo_throughput_mbps: PositiveMetric
    slice_throughput_mbps: NonnegativeMetric
    slice_slo_latency_ms: Annotated[float, Field(strict=True, gt=0, le=60_000)]
    slice_latency_ms: Annotated[float, Field(strict=True, ge=0, le=60_000)]
    nf_cpu_utilization_pct: Percent

    @model_validator(mode="after")
    def failures_do_not_exceed_attempts(self) -> Self:
        """Keep handover counts physically ordered."""
        if self.handover_failures > self.handover_attempts:
            fail_validation("handover_count_order", "handover failures exceed attempts")
        return self


class QualityPolicy(StrictContract):
    """Bounded deterministic thresholds for observation quality."""

    max_age_seconds: Annotated[int, Field(strict=True, ge=1, le=3600)] = 120
    max_prb_spread_pct: Annotated[float, Field(strict=True, gt=0, le=100)] = 25.0
    max_sinr_spread_db: Annotated[float, Field(strict=True, gt=0, le=80)] = 8.0
    max_latency_spread_ms: Annotated[float, Field(strict=True, gt=0, le=60_000)] = 50.0


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


def assess_observation_quality(
    observation: QualityObservation,
    context: QualityContext,
) -> QualityAssessment:
    """Assess all diagnosis evidence without conflating distinct targets."""
    assessed_at = utc_datetime(context.assessed_at)
    evidence_times = (
        *(window.observed_at for window in observation.windows),
        *(alarm.observed_at for alarm in observation.alarms),
        *(config.recorded_at for config in observation.config_history),
    )
    ages = tuple((assessed_at - utc_datetime(value)).total_seconds() for value in evidence_times)
    future = any(age < 0 for age in ages)
    stale = any(age > context.policy.max_age_seconds for age in ages)
    windows_by_target: dict[str, list[MetricWindow]] = {}
    for window in observation.windows:
        windows_by_target.setdefault(window.target_id, []).append(window)
    noisy = False
    for target_windows in windows_by_target.values():
        prb_values = tuple(window.prb_utilization_pct for window in target_windows)
        sinr_values = tuple(window.sinr_db for window in target_windows)
        latency_values = tuple(window.latency_ms for window in target_windows)
        if (
            max(prb_values) - min(prb_values) > context.policy.max_prb_spread_pct
            or max(sinr_values) - min(sinr_values) > context.policy.max_sinr_spread_db
            or max(latency_values) - min(latency_values) > context.policy.max_latency_spread_ms
        ):
            noisy = True
            break
    flags: list[ObservationQualityFlag] = []
    if stale:
        flags.append(ObservationQualityFlag.STALE)
    if future:
        flags.append(ObservationQualityFlag.FUTURE)
    if noisy:
        flags.append(ObservationQualityFlag.NOISY)
    frozen_flags = tuple(flags)
    return QualityAssessment(flags=frozen_flags, approval_eligible=not frozen_flags)
