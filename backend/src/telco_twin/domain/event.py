"""Append-only deterministic simulation-event contract."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from ._contract import ContractId, RootContract, SafeKey, SafeProperties, UtcTimestamp


class Event(RootContract):
    """One event ordered by timestamp, priority, then sequence identifier."""

    event_id: ContractId
    scenario_id: ContractId
    timestamp: UtcTimestamp
    priority: Annotated[int, Field(ge=-1000, le=1000)]
    sequence_id: Annotated[int, Field(ge=0, le=(2**53) - 1)]
    event_type: SafeKey
    payload: SafeProperties
