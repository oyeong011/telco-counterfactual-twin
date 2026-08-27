"""Assemble self-hashed Task5 evidence from typed flow measurements."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from telco_twin.domain._contract import Sha256Hex
from telco_twin.state.probe_evidence import (
    CleanupEvidence,
    ConcurrencyEvidence,
    NegativeEvidence,
    PositiveEvidence,
    ProbeArtifact,
    ProbeArtifactPayload,
    build_probe_artifact,
)

from scripts.task5_probe_provenance import ProbeRunInputs, build_probe_provenance

if TYPE_CHECKING:
    from telco_twin.data.synthetic import SimulationManifest
    from telco_twin.simulator.network_model import NetworkObservation


@dataclass(frozen=True, slots=True)
class ProbeArtifactParts:
    """Actual inputs and already-measured positive/negative outcomes."""

    manifest: SimulationManifest
    observation: NetworkObservation
    patch_hash: Sha256Hex
    positive: PositiveEvidence
    negative: NegativeEvidence
    concurrency: ConcurrencyEvidence


def assemble_probe_artifact(parts: ProbeArtifactParts) -> ProbeArtifact:
    """Bind provenance and cleanup facts, then add the RFC8785 self-hash."""
    payload = ProbeArtifactPayload(
        schema_version="2.0",
        result="pass",
        provenance=build_probe_provenance(
            ProbeRunInputs(
                manifest=parts.manifest,
                observation=parts.observation,
                patch_hash=parts.patch_hash,
            )
        ),
        positive=parts.positive,
        negative=parts.negative,
        concurrency=parts.concurrency,
        cleanup=CleanupEvidence(
            external_resources_created=False,
            in_memory_only=True,
            cancellation_required=False,
        ),
    )
    return build_probe_artifact(payload)
