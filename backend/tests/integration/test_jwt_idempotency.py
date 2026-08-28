"""Session-wide idempotency collisions across demo and JWT authority."""

from fastapi.testclient import TestClient

from telco_twin.api.app import create_app

from .api_test_support import run_approval_flow, session_headers
from .jwt_test_support import jwt_bearer, jwt_fixture


def test_jwt_approval_cannot_reuse_scenario_idempotency_key() -> None:
    # Given: a scenario mutation already owns the session-wide key used by the flow helper.
    fixture = jwt_fixture()
    app = create_app(settings=fixture.settings)
    with TestClient(app) as client:
        flow = run_approval_flow(client)
        # When: JWT approval tries to reuse that key for a different request body/effect.
        response = client.post(
            f"/api/approval-requests/{flow.approval_request_id}/approve",
            headers={
                "Authorization": f"Bearer {jwt_bearer(fixture)}",
                "Idempotency-Key": "idem-scenario-0001",
            },
            json={},
        )
        stream = client.get(
            f"/api/runs/{flow.run_id}/events",
            headers=session_headers(flow.session),
        )
    # Then: collision is 409 and stable SSE IDs remain unique.
    event_ids = tuple(
        line.removeprefix("id: ") for line in stream.text.splitlines() if line.startswith("id: ")
    )
    assert response.status_code == 409
    assert response.json()["code"] == "idempotency_conflict"
    assert len(event_ids) == len(frozenset(event_ids))
