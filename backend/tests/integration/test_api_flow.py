"""Full governed lifecycle and boundary-failure HTTP tests."""

from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from telco_twin.api.app import create_app
from telco_twin.api.contracts import ScenarioListResponse, ScenarioResponse

from .api_test_support import (
    bootstrap,
    create_scenario,
    run_approval_flow,
    session_headers,
)


def test_complete_synthetic_flow_reaches_pending_evidence_without_execution() -> None:
    # Given: one live synthetic demo session.
    with TestClient(create_app()) as client:
        # When: the public lifecycle reaches an approval request.
        flow = run_approval_flow(client)
        scenario_list = client.get(
            "/api/scenarios",
            headers=session_headers(flow.session),
        )
        scenario_read = client.get(
            f"/api/scenarios/{flow.scenario_id}",
            headers=session_headers(flow.session),
        )
        simulation_read = client.get(
            f"/api/simulations/{flow.simulation_id}",
            headers=session_headers(flow.session),
        )
        approval_read = client.get(
            f"/api/approval-requests/{flow.approval_request_id}",
            headers=session_headers(flow.session),
        )
        evidence = client.get(
            f"/api/runs/{flow.run_id}/evidence",
            headers=session_headers(flow.session),
        )
    # Then: all linked evidence is readable and remains pending/non-executing.
    assert scenario_list.status_code == 200
    assert scenario_read.status_code == 200
    assert simulation_read.status_code == 200
    assert approval_read.status_code == 200
    assert approval_read.json()["state"] == "pending"
    assert evidence.status_code == 200
    assert evidence.json()["evidence_card"]["approval_proof_hash"] is None
    assert "execution" not in evidence.text.lower()


def test_mutation_requires_demo_token_and_idempotency_key() -> None:
    # Given: a real session and the scenario creation input.
    with TestClient(create_app()) as client:
        session = bootstrap(client)
        # When: each mandatory authority header is omitted independently.
        missing_token = client.post(
            "/api/scenarios",
            headers={"Origin": "http://localhost:4173", "Idempotency-Key": "idem-missing"},
            json={"fault_family": "radio-congestion", "seed": 7},
        )
        missing_idempotency = client.post(
            "/api/scenarios",
            headers=session_headers(session),
            json={"fault_family": "radio-congestion", "seed": 7},
        )
    # Then: both failures are structured machine-readable problems.
    assert missing_token.status_code == 401
    assert missing_token.headers["content-type"].startswith("application/problem+json")
    assert missing_token.json()["code"] == "demo_token_required"
    assert missing_idempotency.status_code == 400
    assert missing_idempotency.json()["code"] == "idempotency_key_required"


def test_same_idempotency_body_replays_and_changed_body_conflicts() -> None:
    # Given: a session and one accepted scenario creation.
    with TestClient(create_app()) as client:
        session = bootstrap(client)
        first = create_scenario(client, session, key="idem-replay-0001")
        # When: the same key is retried with the same and then a changed body.
        replay = client.post(
            "/api/scenarios",
            headers=session_headers(session, "idem-replay-0001"),
            json={"fault_family": "radio-congestion", "seed": 6701},
        )
        conflict = client.post(
            "/api/scenarios",
            headers=session_headers(session, "idem-replay-0001"),
            json={"fault_family": "backhaul-degradation", "seed": 6702},
        )
    # Then: retry is byte-equivalent while body reuse is a 409 problem.
    assert replay.status_code == 201
    assert ScenarioResponse.model_validate_json(replay.content) == first
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_conflict"


def test_malformed_and_unknown_resources_have_stable_problem_codes() -> None:
    # Given: a live authenticated session.
    with TestClient(create_app()) as client:
        session = bootstrap(client)
        # When: malformed JSON and an unknown scenario are submitted.
        malformed = client.post(
            "/api/scenarios",
            headers={
                **session_headers(session, "idem-malformed-0001"),
                "Content-Type": "application/json",
            },
            content=b"{",
        )
        unknown = client.get(
            "/api/scenarios/scenario-unknown",
            headers=session_headers(session),
        )
    # Then: validation remains 422 and unknown scoped state remains 404.
    assert malformed.status_code == 422
    assert malformed.json()["code"] == "request_validation_failed"
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "scenario_not_found"


def test_benchmark_route_runs_real_determinism_probe() -> None:
    # Given: one live session.
    with TestClient(create_app()) as client:
        session = bootstrap(client)
        # When: the API runs the bounded real simulator benchmark.
        response = client.post(
            "/api/benchmarks",
            headers=session_headers(session, "idem-benchmark-0001"),
            json={"seed": 91, "iterations": 3},
        )
    # Then: all real runs agree on one trace hash.
    assert response.status_code == 200
    assert response.json()["iterations"] == 3
    assert response.json()["unique_trace_hashes"] == 1
    assert response.json()["deterministic"] is True


def test_concurrent_same_idempotency_key_creates_exactly_one_scenario() -> None:
    # Given: one authenticated session and a shared mutation identity.
    with TestClient(create_app()) as client:
        session = bootstrap(client)

        def submit() -> tuple[int, str]:
            response = client.post(
                "/api/scenarios",
                headers=session_headers(session, "idem-concurrent-0001"),
                json={"fault_family": "radio-congestion", "seed": 222},
            )
            scenario = ScenarioResponse.model_validate_json(response.content)
            return response.status_code, scenario.scenario.scenario_id

        def submit_index(_: int) -> tuple[int, str]:
            return submit()

        # When: ten callers race the exact same request.
        with ThreadPoolExecutor(max_workers=10) as pool:
            outcomes = tuple(pool.map(submit_index, range(10)))
        listed = client.get("/api/scenarios", headers=session_headers(session))
    # Then: every response identifies the same sole append-only scenario.
    assert {status for status, _ in outcomes} == {201}
    assert len({scenario_id for _, scenario_id in outcomes}) == 1
    assert len(ScenarioListResponse.model_validate_json(listed.content).items) == 1


def test_malformed_patch_and_cross_session_read_fail_closed() -> None:
    # Given: one scenario and a second unrelated live session.
    with TestClient(create_app()) as client:
        owner = bootstrap(client)
        scenario = create_scenario(client, owner)
        scenario_id = scenario.scenario.scenario_id
        other = bootstrap(client)
        # When: a forbidden patch operation and cross-session read are attempted.
        malformed = client.post(
            f"/api/scenarios/{scenario_id}/patches",
            headers=session_headers(owner, "idem-malformed-patch"),
            json={
                "patch_id": "patch-malformed",
                "scenario_id": scenario_id,
                "base_topology_hash": scenario.topology_hash,
                "changes": [
                    {
                        "target_id": "cell-0001",
                        "target_kind": "cell",
                        "operation": "execute",
                        "parameters": {"capacity_ues": 230},
                    }
                ],
                "blast_radius": {
                    "max_cells": 1,
                    "max_ue_cohorts": 1,
                    "max_slices": 1,
                },
                "proposed_at": scenario.scenario.starts_at,
                "schema_version": "1.0",
            },
        )
        cross_session = client.get(
            f"/api/scenarios/{scenario_id}",
            headers=session_headers(other),
        )
    # Then: malformed authority is 422 and ownership remains non-enumerable 404.
    assert malformed.status_code == 422
    assert malformed.json()["code"] == "request_validation_failed"
    assert cross_session.status_code == 404
    assert cross_session.json()["code"] == "scenario_not_found"
