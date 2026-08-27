"""Valid JSON payload builders for strict contract tests."""

from __future__ import annotations

from pydantic import BaseModel, JsonValue

from telco_twin.domain.event import Event
from telco_twin.domain.evidence import EvidenceCard
from telco_twin.domain.intervention import TypedPatch
from telco_twin.domain.scenario import Scenario
from telco_twin.domain.simulation_result import SimulationResult
from telco_twin.domain.telemetry import Telemetry
from telco_twin.domain.topology import Topology

type JsonObject = dict[str, JsonValue]


def topology_payload() -> JsonObject:
    """Return the smallest topology containing every required synthetic family."""
    nodes: list[JsonValue] = [
        {"node_id": node_id, "kind": kind, "attributes": {}}
        for node_id, kind in (
            ("cell-0001", "cell"),
            ("cell-0002", "cell"),
            ("gnb-0001", "gnb"),
            ("ue-cohort-0001", "ue-cohort"),
            ("backhaul-0001", "backhaul"),
            ("amf-0001", "amf"),
            ("smf-0001", "smf"),
            ("upf-0001", "upf"),
            ("slice-0001", "slice"),
        )
    ]
    return {
        "topology_id": "topology-0001",
        "seed": 20260827,
        "nodes": nodes,
        "links": [
            {
                "link_id": "link-0001",
                "source_id": "gnb-0001",
                "target_id": "upf-0001",
                "capacity_mbps": 1000.0,
                "latency_ms": 5.0,
            }
        ],
        "config_history": [
            {
                "config_version": "config-0001",
                "recorded_at": "2026-08-27T00:00:00Z",
                "changes": {"scheduler_weight": 10},
            }
        ],
        "schema_version": "1.0",
    }


def patch_payload() -> JsonObject:
    """Return one bounded simulation-only candidate patch."""
    return {
        "patch_id": "patch-0001",
        "scenario_id": "scenario-0001",
        "base_topology_hash": "a" * 64,
        "changes": [
            {
                "target_id": "slice-0001",
                "target_kind": "slice",
                "operation": "rebalance-slice-weight",
                "parameters": {"weight": 20},
            }
        ],
        "blast_radius": {"max_cells": 1, "max_ue_cohorts": 2, "max_slices": 1},
        "proposed_at": "2026-08-27T00:00:00Z",
        "schema_version": "1.0",
    }


def build_identity_payloads(empty_hash: str) -> tuple[JsonObject, JsonObject]:
    """Return component-specific identities with no digest-field overlap."""
    common: JsonObject = {
        "service_name": "twin-api",
        "version": "0.1.0",
        "runtime_source_commit_sha": "1" * 40,
        "release_commit_sha": "2" * 40,
        "runtime_tree_hash": "3" * 64,
        "schema_hashes": {"scenario": "4" * 64},
        "mcp_hash": empty_hash,
        "policy_hash": empty_hash,
        "trusted_root_hashes": empty_hash,
        "built_at": "2026-08-27T00:00:00Z",
        "schema_version": "1.0",
    }
    service: JsonObject = {
        **common,
        "image_digest": f"sha256:{'6' * 64}",
        "digest_scope": "registry_manifest",
    }
    ui: JsonObject = {
        **common,
        "service_name": "twin-ui",
        "asset_manifest_hash": "7" * 64,
    }
    return service, ui


def valid_domain_cases() -> tuple[tuple[type[BaseModel], JsonObject], ...]:
    """Return one valid boundary object for each non-approval domain schema."""
    return (
        (Topology, topology_payload()),
        (
            Telemetry,
            {
                "telemetry_id": "telemetry-0001",
                "topology_id": "topology-0001",
                "samples": [
                    {
                        "metric_name": "prb-utilization",
                        "target_id": "cell-0001",
                        "value": 81.5,
                        "unit": "percent",
                        "observed_at": "2026-08-27T00:00:00Z",
                        "quality": "fresh",
                    }
                ],
                "schema_version": "1.0",
            },
        ),
        (
            Scenario,
            {
                "scenario_id": "scenario-0001",
                "topology_id": "topology-0001",
                "seed": 7,
                "fault_family": "radio-congestion",
                "starts_at": "2026-08-27T00:00:00Z",
                "duration_seconds": 60,
                "target_ids": ["cell-0001"],
                "parameters": {"load_percent": 95},
                "schema_version": "1.0",
            },
        ),
        (
            Event,
            {
                "event_id": "event-0001",
                "scenario_id": "scenario-0001",
                "timestamp": "2026-08-27T00:00:01Z",
                "priority": 10,
                "sequence_id": 1,
                "event_type": "metric-sampled",
                "payload": {"sample_count": 1},
                "schema_version": "1.0",
            },
        ),
        (TypedPatch, patch_payload()),
        (
            SimulationResult,
            {
                "simulation_id": "simulation-0001",
                "scenario_id": "scenario-0001",
                "patch_hash": "b" * 64,
                "baseline_hash": "c" * 64,
                "candidate_hash": "d" * 64,
                "trace_hash": "e" * 64,
                "started_at": "2026-08-27T00:00:00Z",
                "completed_at": "2026-08-27T00:00:10Z",
                "metric_deltas": [
                    {
                        "metric_name": "latency-p95",
                        "baseline": 100.0,
                        "candidate": 80.0,
                        "unit": "milliseconds",
                    }
                ],
                "constraints": [
                    {
                        "constraint_code": "slice-slo",
                        "passed": True,
                        "evidence_hash": "f" * 64,
                    }
                ],
                "approval_eligible": True,
                "schema_version": "1.0",
            },
        ),
        (
            EvidenceCard,
            {
                "evidence_id": "evidence-0001",
                "session_id": "session-0001",
                "scenario_hash": "1" * 64,
                "patch_hash": "2" * 64,
                "simulation_hash": "3" * 64,
                "policy_hash": "4" * 64,
                "approval_proof_hash": "5" * 64,
                "seed": 7,
                "source_commit_sha": "6" * 40,
                "contract_hashes": {"scenario": "7" * 64},
                "generated_at": "2026-08-27T00:00:00Z",
                "schema_version": "1.0",
            },
        ),
    )
