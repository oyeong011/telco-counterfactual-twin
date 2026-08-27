"""Synthetic telemetry observation contract."""

from __future__ import annotations

from enum import StrEnum, unique
from typing import Annotated

from pydantic import Field

from ._contract import ContractId, RootContract, SafeKey, StrictContract, UtcTimestamp


@unique
class ObservationQuality(StrEnum):
    """Quality boundary carried by every observation."""

    FRESH = "fresh"
    STALE = "stale"
    NOISY = "noisy"


class MetricSample(StrictContract):
    """One bounded synthetic metric sample without subscriber identity."""

    metric_name: SafeKey
    target_id: ContractId
    value: Annotated[float, Field(ge=-1_000_000_000, le=1_000_000_000)]
    unit: SafeKey
    observed_at: UtcTimestamp
    quality: ObservationQuality


class Telemetry(RootContract):
    """Immutable metric batch bound to one topology."""

    telemetry_id: ContractId
    topology_id: ContractId
    samples: Annotated[tuple[MetricSample, ...], Field(min_length=1, max_length=1024)]
