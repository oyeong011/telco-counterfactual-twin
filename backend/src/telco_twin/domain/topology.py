"""Synthetic topology snapshot contract."""

from __future__ import annotations

from enum import StrEnum, unique
from typing import Annotated, Final, Self

from pydantic import Field, model_validator

from ._contract import (
    ContractId,
    RootContract,
    SafeProperties,
    Seed,
    StrictContract,
    UtcTimestamp,
    fail_validation,
)

MIN_CELLS: Final = 2
MAX_CELLS: Final = 4


@unique
class NodeKind(StrEnum):
    """Permitted synthetic topology node families."""

    CELL = "cell"
    GNB = "gnb"
    UE_COHORT = "ue-cohort"
    BACKHAUL = "backhaul"
    AMF = "amf"
    SMF = "smf"
    UPF = "upf"
    SLICE = "slice"


class TopologyNode(StrictContract):
    """One synthetic, non-subscriber topology node."""

    node_id: ContractId
    kind: NodeKind
    attributes: SafeProperties = Field(default_factory=dict)


class TopologyLink(StrictContract):
    """One bounded directed link between known nodes."""

    link_id: ContractId
    source_id: ContractId
    target_id: ContractId
    capacity_mbps: Annotated[float, Field(gt=0, le=1_000_000)]
    latency_ms: Annotated[float, Field(ge=0, le=60_000)]


class ConfigRecord(StrictContract):
    """Immutable synthetic configuration-history record."""

    config_version: ContractId
    recorded_at: UtcTimestamp
    changes: SafeProperties


class Topology(RootContract):
    """Bounded topology required by every deterministic scenario."""

    topology_id: ContractId
    seed: Seed
    nodes: Annotated[tuple[TopologyNode, ...], Field(min_length=9, max_length=64)]
    links: Annotated[tuple[TopologyLink, ...], Field(min_length=1, max_length=128)]
    config_history: Annotated[tuple[ConfigRecord, ...], Field(min_length=1, max_length=128)]

    @model_validator(mode="after")
    def topology_is_bounded_and_connected(self) -> Self:
        """Require two-to-four cells, core families, unique IDs, and valid links."""
        node_ids = [node.node_id for node in self.nodes]
        link_ids = [link.link_id for link in self.links]
        if len(set(node_ids)) != len(node_ids) or len(set(link_ids)) != len(link_ids):
            fail_validation("duplicate_identifier", "topology identifiers must be unique")
        cell_count = sum(node.kind is NodeKind.CELL for node in self.nodes)
        if not MIN_CELLS <= cell_count <= MAX_CELLS:
            fail_validation("bounded_cell_count", "topology requires two to four cells")
        required = set(NodeKind)
        if {node.kind for node in self.nodes} != required:
            fail_validation("topology_family_missing", "topology node family is missing")
        known = set(node_ids)
        if any(link.source_id not in known or link.target_id not in known for link in self.links):
            fail_validation("unknown_link_endpoint", "topology link endpoint is unknown")
        return self
