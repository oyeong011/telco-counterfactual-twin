"""Scoped stable SSE replay and reconnect tests."""

from fastapi.testclient import TestClient

from telco_twin.api.app import create_app

from .api_test_support import create_scenario, run_approval_flow, session_headers


def _event_ids(body: str) -> tuple[str, ...]:
    return tuple(line.removeprefix("id: ") for line in body.splitlines() if line.startswith("id: "))


def test_sse_reconnect_replays_only_events_after_scoped_last_event_id() -> None:
    # Given: one completed governed run with multiple append-only events.
    with TestClient(create_app()) as client:
        flow = run_approval_flow(client)
        first = client.get(
            f"/api/runs/{flow.run_id}/events",
            headers=session_headers(flow.session),
        )
        ids = _event_ids(first.text)
        # When: the client reconnects from the first stable event ID.
        reconnect = client.get(
            f"/api/runs/{flow.run_id}/events",
            headers={**session_headers(flow.session), "Last-Event-ID": ids[0]},
        )
    # Then: the cursor event is not duplicated and later IDs retain order.
    assert first.status_code == 200
    assert first.headers["content-type"].startswith("text/event-stream")
    assert len(ids) >= 5
    assert _event_ids(reconnect.text) == ids[1:]
    assert ": heartbeat" in reconnect.text


def test_sse_rejects_gap_and_cursor_from_another_run() -> None:
    # Given: two distinct run streams in one authenticated session.
    with TestClient(create_app()) as client:
        flow = run_approval_flow(client)
        first_stream = client.get(
            f"/api/runs/{flow.run_id}/events",
            headers=session_headers(flow.session),
        )
        other_scenario = create_scenario(client, flow.session, key="idem-scenario-other")
        other_run_id = other_scenario.run_id
        wrong_stream_id = _event_ids(first_stream.text)[0]
        # When: cursor is unknown and then valid only for another run.
        gap = client.get(
            f"/api/runs/{flow.run_id}/events",
            headers={
                **session_headers(flow.session),
                "Last-Event-ID": "event-unknown-gap",
            },
        )
        wrong = client.get(
            f"/api/runs/{other_run_id}/events",
            headers={**session_headers(flow.session), "Last-Event-ID": wrong_stream_id},
        )
    # Then: neither cursor can replay from the wrong bounded stream.
    assert gap.status_code == 409
    assert gap.json()["code"] == "sse_replay_gap"
    assert wrong.status_code == 409
    assert wrong.json()["code"] == "sse_cursor_wrong_stream"
