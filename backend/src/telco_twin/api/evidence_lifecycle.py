"""Run-scoped SSE replay and downloadable evidence assembly."""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from telco_twin.api.contracts import EvidenceResponse
from telco_twin.api.errors import ProblemError
from telco_twin.domain.event import Event
from telco_twin.domain.evidence import EvidenceCard
from telco_twin.state.trusted_clock import trusted_timestamp

if TYPE_CHECKING:
    from telco_twin.api.runtime import ApiRuntime, AuthorizedSession
    from telco_twin.simulator.frozen_event import FrozenEvent


def _thaw(event: FrozenEvent) -> Event:
    return Event.model_validate(event.model_dump())


@final
class EvidenceLifecycle:
    """Read only the authenticated session's bounded run evidence."""

    def __init__(self, runtime: ApiRuntime) -> None:
        """Bind evidence reads to one process runtime."""
        self._runtime = runtime

    async def events(
        self,
        authorized: AuthorizedSession,
        run_id: str,
    ) -> tuple[FrozenEvent, ...]:
        """Return one existing run's stable event stream in append order."""
        if run_id not in authorized.session.runs:
            raise ProblemError(
                404,
                "run_not_found",
                "Run not found",
                "The run does not exist in this live session.",
            )
        snapshot = await self._runtime.snapshot(authorized.token)
        all_events = tuple(
            sorted(
                (*snapshot.events, *authorized.session.external_events),
                key=lambda event: event.sequence_id,
            )
        )
        return tuple(event for event in all_events if event.payload.get("run_id") == run_id)

    async def reconnect(
        self,
        authorized: AuthorizedSession,
        run_id: str,
        last_event_id: str | None,
    ) -> tuple[FrozenEvent, ...]:
        """Apply a run-scoped cursor without accepting gaps or another stream."""
        stream = await self.events(authorized, run_id)
        if last_event_id is None:
            return stream
        index = next(
            (position for position, event in enumerate(stream) if event.event_id == last_event_id),
            None,
        )
        if index is not None:
            return stream[index + 1 :]
        snapshot = await self._runtime.snapshot(authorized.token)
        if any(
            event.event_id == last_event_id
            for event in (*snapshot.events, *authorized.session.external_events)
        ):
            raise ProblemError(
                409,
                "sse_cursor_wrong_stream",
                "SSE cursor belongs to another stream",
                "Last-Event-ID is scoped to a different run.",
            )
        raise ProblemError(
            409,
            "sse_replay_gap",
            "SSE replay gap",
            "Last-Event-ID is outside the bounded replay window.",
        )

    async def evidence(
        self,
        authorized: AuthorizedSession,
        run_id: str,
    ) -> EvidenceResponse:
        """Assemble one portable card from actual stored lifecycle identities."""
        session = authorized.session
        async with session.lock:
            run = session.runs.get(run_id)
            if run is None:
                raise ProblemError(
                    404,
                    "run_not_found",
                    "Run not found",
                    "The run does not exist in this live session.",
                )
            if (
                run.patch_id is None
                or run.simulation_id is None
                or run.comparison_id is None
                or run.approval_request_id is None
            ):
                raise ProblemError(
                    409,
                    "evidence_incomplete",
                    "Evidence incomplete",
                    "The governed lifecycle is incomplete for this run.",
                )
            scenario = session.scenarios[run.scenario_id]
            patch = session.patches[run.patch_id]
            approval = session.approval_requests[run.approval_request_id]
            record = await session.approvals.get(run.approval_request_id)
            if record is None:
                raise ProblemError(
                    503,
                    "approval_state_unavailable",
                    "Approval state unavailable",
                    "The approval evidence state is unavailable.",
                )
            simulation_hash = approval.policy.evidence.simulation_hash
            if simulation_hash is None:
                raise ProblemError(
                    503,
                    "policy_provenance_unavailable",
                    "Policy provenance unavailable",
                    "The retained policy lacks a simulation hash.",
                )
            card = EvidenceCard(
                evidence_id=approval.evidence_id,
                session_id=session.session_id,
                scenario_hash=scenario.manifest.scenario_hash,
                patch_hash=patch.patch_hash,
                simulation_hash=simulation_hash,
                policy_hash=approval.policy.evidence.policy_hash,
                approval_proof_hash=record.proof_hash,
                seed=scenario.manifest.seed,
                source_commit_sha=self._runtime.settings.runtime_source_commit_sha,
                contract_hashes=dict(self._runtime.build_info.schema_hashes),
                generated_at=trusted_timestamp(self._runtime.clock),
                schema_version="1.0",
            )
            snapshot = await self._runtime.snapshot(authorized.token)
            events = tuple(
                _thaw(event)
                for event in sorted(
                    (*snapshot.events, *session.external_events),
                    key=lambda item: item.sequence_id,
                )
                if event.payload.get("run_id") == run_id
            )
            return EvidenceResponse(
                run_id=run_id,
                evidence_card=card,
                events=events,
                approval_proof=approval.proof,
            )
