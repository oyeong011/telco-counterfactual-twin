"""HTTP helpers that drive the real FastAPI application boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from telco_twin.api.contracts import (
    ApprovalRequestResponse,
    DemoSessionResponse,
    PatchResponse,
    ScenarioResponse,
    SimulationResponse,
)

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from pydantic import JsonValue

    from telco_twin.domain.approval import SessionKeyCertificate

ALLOWED_ORIGIN = "http://localhost:4173"


@dataclass(frozen=True, slots=True)
class DemoSession:
    session_id: str
    token: str
    certificate: SessionKeyCertificate


@dataclass(frozen=True, slots=True)
class ApprovalFlow:
    session: DemoSession
    scenario_id: str
    patch_id: str
    simulation_id: str
    run_id: str
    approval_request_id: str


@dataclass(frozen=True, slots=True)
class ComparisonFlow:
    session: DemoSession
    scenario_id: str
    simulation_id: str
    run_id: str


@dataclass(frozen=True, slots=True)
class SimulationFlow:
    session: DemoSession
    scenario_id: str
    simulation_id: str
    run_id: str


def bootstrap(client: TestClient, *, origin: str = ALLOWED_ORIGIN) -> DemoSession:
    response = client.post(
        "/api/demo-sessions",
        headers={"Origin": origin},
        json={"synthetic_only": True},
    )
    assert response.status_code == 201, response.text
    body = DemoSessionResponse.model_validate_json(response.content)
    return DemoSession(
        session_id=body.session_id,
        token=body.demo_token,
        certificate=body.session_certificate,
    )


def session_headers(session: DemoSession, idempotency_key: str | None = None) -> dict[str, str]:
    headers = {
        "Origin": ALLOWED_ORIGIN,
        "X-Demo-Session-Token": session.token,
    }
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def create_scenario(
    client: TestClient,
    session: DemoSession,
    *,
    key: str = "idem-scenario-0001",
) -> ScenarioResponse:
    response = client.post(
        "/api/scenarios",
        headers=session_headers(session, key),
        json={"fault_family": "radio-congestion", "seed": 6701},
    )
    assert response.status_code == 201, response.text
    return ScenarioResponse.model_validate_json(response.content)


def run_to_simulation(client: TestClient) -> SimulationFlow:
    session = bootstrap(client)
    scenario = create_scenario(client, session)
    scenario_id = scenario.scenario.scenario_id
    diagnose = client.post(
        f"/api/scenarios/{scenario_id}/diagnose",
        headers=session_headers(session, "idem-diagnose-0001"),
        json={},
    )
    assert diagnose.status_code == 200, diagnose.text
    patch_body: JsonValue = {
        "patch_id": "patch-flow-0001",
        "scenario_id": scenario_id,
        "base_topology_hash": scenario.topology_hash,
        "changes": [
            {
                "target_id": "cell-0001",
                "target_kind": "cell",
                "operation": "adjust-radio-capacity",
                "parameters": {"capacity_ues": 230},
            }
        ],
        "blast_radius": {"max_cells": 1, "max_ue_cohorts": 1, "max_slices": 1},
        "proposed_at": scenario.scenario.starts_at,
        "schema_version": "1.0",
    }
    patch = client.post(
        f"/api/scenarios/{scenario_id}/patches",
        headers=session_headers(session, "idem-patch-0001"),
        json=patch_body,
    )
    assert patch.status_code == 201, patch.text
    patch_id = PatchResponse.model_validate_json(patch.content).patch.patch_id
    simulation = client.post(
        f"/api/patches/{patch_id}/simulations",
        headers=session_headers(session, "idem-simulation-0001"),
        json={},
    )
    assert simulation.status_code == 201, simulation.text
    simulation_body = SimulationResponse.model_validate_json(simulation.content)
    simulation_id = simulation_body.simulation_id
    run_id = simulation_body.run_id
    return SimulationFlow(session, scenario_id, simulation_id, run_id)


def run_to_comparison(client: TestClient) -> ComparisonFlow:
    simulation = run_to_simulation(client)
    comparison = client.post(
        f"/api/simulations/{simulation.simulation_id}/comparisons",
        headers=session_headers(simulation.session, "idem-comparison-0001"),
        json={},
    )
    assert comparison.status_code == 201, comparison.text
    return ComparisonFlow(
        simulation.session,
        simulation.scenario_id,
        simulation.simulation_id,
        simulation.run_id,
    )


def run_approval_flow(client: TestClient) -> ApprovalFlow:
    comparison = run_to_comparison(client)
    approval = client.post(
        f"/api/simulations/{comparison.simulation_id}/approval-requests",
        headers=session_headers(comparison.session, "idem-approval-request-0001"),
        json={},
    )
    assert approval.status_code == 201, approval.text
    return ApprovalFlow(
        session=comparison.session,
        scenario_id=comparison.scenario_id,
        patch_id="patch-flow-0001",
        simulation_id=comparison.simulation_id,
        run_id=comparison.run_id,
        approval_request_id=ApprovalRequestResponse.model_validate_json(
            approval.content
        ).approval_request.request_id,
    )
