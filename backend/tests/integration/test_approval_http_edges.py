"""Adversarial approval/session branches beyond the primary lifecycle story."""
# pyright: reportPrivateUsage=false

from datetime import timedelta

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from httpx2 import Response

from telco_twin.api.app import create_app
from telco_twin.state.limits import MAX_EVENTS_PER_SESSION

from .api_test_support import (
    bootstrap,
    run_approval_flow,
    run_to_comparison,
    run_to_simulation,
    session_headers,
)
from .jwt_test_support import JwtTokenSpec, jwt_bearer, jwt_fixture


def test_approval_requires_comparison_and_same_request_idempotency_replays() -> None:
    # Given: one simulation before comparison and one complete comparison in another app.
    with TestClient(create_app()) as client:
        incomplete = run_to_simulation(client)
        # When: approval is requested too early.
        missing_comparison = client.post(
            f"/api/simulations/{incomplete.simulation_id}/approval-requests",
            headers=session_headers(incomplete.session, "idem-early-approval"),
            json={},
        )
    with TestClient(create_app()) as client:
        flow = run_to_comparison(client)
        headers = session_headers(flow.session, "idem-approval-request-replay")
        first = client.post(
            f"/api/simulations/{flow.simulation_id}/approval-requests",
            headers=headers,
            json={},
        )
        replay = client.post(
            f"/api/simulations/{flow.simulation_id}/approval-requests",
            headers=headers,
            json={},
        )
    # Then: ordering is enforced and exact retry returns the original request.
    assert missing_comparison.status_code == 409
    assert missing_comparison.json()["code"] == "comparison_required"
    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json() == first.json()
    assert replay.headers["Idempotency-Replayed"] == "true"


def test_unknown_simulation_and_approval_request_are_session_scoped_404s() -> None:
    # Given: one authenticated session with no matching resources.
    with TestClient(create_app()) as client:
        session = bootstrap(client)
        # When: downstream approval surfaces receive unknown IDs.
        simulation = client.post(
            "/api/simulations/simulation-unknown/approval-requests",
            headers=session_headers(session, "idem-unknown-simulation"),
            json={},
        )
        approval = client.get(
            "/api/approval-requests/approval-request-unknown",
            headers=session_headers(session),
        )
    # Then: neither ID leaks cross-session or global state.
    assert simulation.status_code == 404
    assert simulation.json()["code"] == "simulation_not_found"
    assert approval.status_code == 404
    assert approval.json()["code"] == "approval_request_not_found"


def test_demo_terminal_decision_replays_same_key_and_rejects_new_key() -> None:
    # Given: one pending request.
    with TestClient(create_app()) as client:
        flow = run_approval_flow(client)
        target = f"/api/approval-requests/{flow.approval_request_id}/approve"
        headers = session_headers(flow.session, "idem-terminal-replay")
        # When: approval is submitted, retried, then repeated under a new key.
        first = client.post(target, headers=headers, json={})
        replay = client.post(target, headers=headers, json={})
        conflict = client.post(
            target,
            headers=session_headers(flow.session, "idem-terminal-other"),
            json={},
        )
    # Then: only the original idempotent decision remains valid.
    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "approval_already_terminal"


def test_forged_token_and_unavailable_store_fail_with_distinct_problems() -> None:
    # Given: one authentic live session.
    app = create_app()
    with TestClient(app) as client:
        session = bootstrap(client)
        forged_value = session.token[:-1] + ("A" if session.token[-1] != "A" else "B")
        # When: a forgery is used and then the state dependency degrades.
        forged = client.get(
            "/api/scenarios",
            headers={"X-Demo-Session-Token": forged_value},
        )
        app.runtime.set_available(False)
        unavailable = client.get("/api/scenarios", headers=session_headers(session))
    # Then: credential failure is 401 while dependency failure is 503.
    assert forged.status_code == 401
    assert forged.json()["code"] == "demo_token_invalid"
    assert unavailable.status_code == 503
    assert unavailable.json()["code"] == "state_store_unavailable"


def test_configured_jwt_rejects_role_signature_time_and_unknown_request() -> None:
    # Given: a configured app and one pending approval request.
    fixture = jwt_fixture()
    with TestClient(create_app(settings=fixture.settings)) as client:
        flow = run_approval_flow(client)

        def submit(token: str, request_id: str = flow.approval_request_id) -> Response:
            return client.post(
                f"/api/approval-requests/{request_id}/approve",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Idempotency-Key": f"idem-{request_id}",
                },
                json={},
            )

        # When: each independently invalid bearer class is submitted.
        wrong_role = submit(jwt_bearer(fixture, JwtTokenSpec(roles=("viewer",))))
        bad_signature = submit(
            jwt_bearer(
                fixture,
                JwtTokenSpec(signing_key=Ed25519PrivateKey.generate()),
            )
        )
        expired = submit(jwt_bearer(fixture, JwtTokenSpec(expires_in=timedelta(seconds=-1))))
        wrong_key_id = submit(jwt_bearer(fixture, JwtTokenSpec(key_id="approver-key-unknown")))
        malformed_parts = submit("not-a-jwt")
        malformed_encoding = submit("a.b.c")
        wrong_scheme = client.post(
            f"/api/approval-requests/{flow.approval_request_id}/approve",
            headers={
                "Authorization": "Basic not-a-bearer",
                "Idempotency-Key": "idem-wrong-scheme",
            },
            json={},
        )
        unknown = submit(jwt_bearer(fixture), "approval-request-unknown")
    # Then: role is forbidden, invalid bearers unauthorized, and unknown state hidden.
    assert wrong_role.status_code == 403
    assert wrong_role.json()["code"] == "approver_role_required"
    assert bad_signature.status_code == 401
    assert expired.status_code == 401
    assert wrong_key_id.status_code == 401
    assert malformed_parts.status_code == 401
    assert malformed_encoding.status_code == 401
    assert wrong_scheme.status_code == 401
    assert unknown.status_code == 404


def test_jwt_terminal_decision_replays_and_conflicts_without_demo_token() -> None:
    # Given: one configured JWT approver and pending request.
    fixture = jwt_fixture()
    bearer = jwt_bearer(fixture)
    with TestClient(create_app(settings=fixture.settings)) as client:
        flow = run_approval_flow(client)
        target = f"/api/approval-requests/{flow.approval_request_id}/approve"
        headers = {
            "Authorization": f"Bearer {bearer}",
            "Idempotency-Key": "idem-jwt-terminal",
        }
        # When: the JWT decision is repeated and then changed under a new key.
        first = client.post(target, headers=headers, json={})
        replay = client.post(target, headers=headers, json={})
        conflict = client.post(
            target,
            headers={**headers, "Idempotency-Key": "idem-jwt-terminal-other"},
            json={},
        )
    # Then: JWT idempotency has the same terminal guarantees as demo authority.
    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert conflict.status_code == 409


def test_jwt_decision_respects_combined_session_event_capacity() -> None:
    # Given: a pending request whose shared API event sequence is at capacity.
    fixture = jwt_fixture()
    bearer = jwt_bearer(fixture)
    app = create_app(settings=fixture.settings)
    with TestClient(app) as client:
        flow = run_approval_flow(client)
        app.runtime._sessions[flow.session.session_id].next_event_sequence = MAX_EVENTS_PER_SESSION
        # When: JWT authority attempts to append another terminal event.
        response = client.post(
            f"/api/approval-requests/{flow.approval_request_id}/approve",
            headers={
                "Authorization": f"Bearer {bearer}",
                "Idempotency-Key": "idem-jwt-capacity",
            },
            json={},
        )
    # Then: the same 256-event session bound applies without a persisted demo token.
    assert response.status_code == 429
    assert response.json()["code"] == "demo_event_capacity"
