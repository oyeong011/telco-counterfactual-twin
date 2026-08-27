"""Strict immutable telecom metric values shared by model and quality layers."""

from __future__ import annotations

from typing import Annotated, Self

from pydantic import Field, model_validator

from telco_twin.domain._contract import ContractId, StrictContract, UtcTimestamp
from telco_twin.domain._validation import fail_validation

type Percent = Annotated[float, Field(strict=True, ge=0, le=100)]
type NonnegativeMetric = Annotated[float, Field(strict=True, ge=0, le=1_000_000)]
type PositiveMetric = Annotated[float, Field(strict=True, gt=0, le=1_000_000)]


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
