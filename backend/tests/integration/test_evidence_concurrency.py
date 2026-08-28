"""Concurrency consistency between evidence download and terminal approval."""

from __future__ import annotations

from typing import TYPE_CHECKING

import anyio
from fastapi.testclient import TestClient

from telco_twin.api.app import create_app
from telco_twin.api.approval_lifecycle import ApprovalLifecycle
from telco_twin.api.contracts import ApprovalDecisionResponse, EmptyRequest, EvidenceResponse
from telco_twin.api.evidence_lifecycle import EvidenceLifecycle
from telco_twin.domain.approval import ApprovalDecision

from .api_test_support import run_approval_flow

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    import pytest

    from telco_twin.state.store_models import SessionSnapshot


def test_evidence_snapshot_holds_session_lock_until_events_are_captured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one pending run and a controllably blocked Task 5 snapshot.
    app = create_app()
    with TestClient(app) as client:
        flow = run_approval_flow(client)
    authorized = anyio.run(app.runtime.authorize, flow.session.token)
    evidence_lifecycle = EvidenceLifecycle(app.runtime)
    approval_lifecycle = ApprovalLifecycle(app.runtime)
    original_snapshot: Callable[[str], Awaitable[SessionSnapshot]] = app.runtime.snapshot

    async def scenario() -> None:
        snapshot_entered = anyio.Event()
        release_snapshot = anyio.Event()
        decision_finished = anyio.Event()
        first_snapshot = True
        evidence_results: list[EvidenceResponse] = []
        decision_results: list[ApprovalDecisionResponse] = []

        async def blocked_snapshot(token: str) -> SessionSnapshot:
            nonlocal first_snapshot
            if first_snapshot:
                first_snapshot = False
                snapshot_entered.set()
                await release_snapshot.wait()
            return await original_snapshot(token)

        async def read_evidence() -> None:
            evidence_results.append(await evidence_lifecycle.evidence(authorized, flow.run_id))

        async def approve() -> None:
            decision, _ = await approval_lifecycle.decide_demo(
                authorized,
                flow.approval_request_id,
                "idem-concurrent-evidence-approval",
                EmptyRequest(),
                ApprovalDecision.APPROVED,
            )
            decision_results.append(decision)
            decision_finished.set()

        monkeypatch.setattr(app.runtime, "snapshot", blocked_snapshot)
        async with anyio.create_task_group() as group:
            _ = group.start_soon(read_evidence)
            await snapshot_entered.wait()
            _ = group.start_soon(approve)
            with anyio.move_on_after(0.05) as scope:
                await decision_finished.wait()
            assert scope.cancelled_caught is True
            release_snapshot.set()
        assert len(evidence_results) == 1
        assert len(decision_results) == 1
        assert evidence_results[0].evidence_card.approval_proof_hash is None
        assert evidence_results[0].approval_proof is None

    anyio.run(scenario)
