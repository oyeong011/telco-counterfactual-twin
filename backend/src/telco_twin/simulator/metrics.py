"""Typed metric windows and fail-closed observation-quality boundaries."""

from __future__ import annotations

from enum import StrEnum, unique
from typing import TYPE_CHECKING, Annotated, Self

from pydantic import Field, model_validator

from telco_twin.domain._contract import StrictContract, UtcTimestamp, utc_datetime
from telco_twin.domain._validation import fail_validation
from telco_twin.simulator.metric_values import MetricWindow

__all__ = ("MetricWindow",)

if TYPE_CHECKING:
    from telco_twin.simulator.network_model import NetworkObservation


@unique
class ObservationQualityFlag(StrEnum):
    """Machine-readable reasons an observation cannot support approval."""

    STALE = "stale-window"
    FUTURE = "future-evidence"
    NOISY = "noisy-window"


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
    observation: NetworkObservation,
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
