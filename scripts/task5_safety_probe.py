# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["anyio>=4,<5", "pydantic==2.13.4", "pynacl>=1.6.2,<2"]
# ///
# ─── How to run ───
# uv run --project backend python -m scripts.task5_safety_probe --out artifacts/task5-probe.json
"""Run the real Task5 evidence-only lifecycle and stable negative paths."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import anyio
from telco_twin.approval.authority import (
    ApprovalProofIssue,
    ApprovalRequestIssue,
    AuthorityMode,
    SessionIssue,
    issue_approval_request,
    load_approval_authority,
)
from telco_twin.approval.state_machine import ApprovalStateMachine
from telco_twin.counterfactual.comparison import compare_counterfactual, hash_comparison
from telco_twin.counterfactual.patches import PatchRejected, assess_patch
from telco_twin.counterfactual.runner import CounterfactualRun, run_counterfactual
from telco_twin.data.synthetic import generate_manifest
from telco_twin.domain.approval import (
    ApprovalDecision,
    ApprovalValidationContext,
    ContractViolationError,
    Environment,
    validate_approval_chain,
)
from telco_twin.safety.local_policy import evaluate_local_policy
from telco_twin.simulator.engine import ManifestIntegrityError, run_simulation
from telco_twin.simulator.metrics import ObservationQualityFlag, QualityAssessment
from telco_twin.state.memory_store import (
    AppendEventRequest,
    DemoSessionStore,
    EventAppendAccepted,
    SessionAccess,
    SessionAccessDenied,
    SessionAccessGranted,
    SessionCreate,
    SessionCreateDenied,
)

from scripts.task5_probe_support import (
    DEMO_KEY,
    NOW,
    CleanupEvidence,
    ConcurrencyEvidence,
    NegativeEvidence,
    PositiveEvidence,
    ProbeArtifact,
    ProbeInvariantCode,
    ProbeInvariantError,
    ProbeUsageError,
    probe_event,
    probe_patch,
    probe_policy_input,
    probe_snapshot_hash,
)


async def _run_probe() -> ProbeArtifact:
    manifest = generate_manifest(91)
    patch = probe_patch()
    baseline_before = run_simulation(manifest).trace_hash
    run = run_counterfactual(manifest, patch)
    if not isinstance(run, CounterfactualRun):
        raise ProbeInvariantError(ProbeInvariantCode.COUNTERFACTUAL)
    comparison = compare_counterfactual(run, "simulation-probe-0001")
    simulation_hash = hash_comparison(comparison)
    policy_input = probe_policy_input(run, comparison)
    policy = evaluate_local_policy(policy_input)
    authority = load_approval_authority(AuthorityMode.LOCAL)
    session = authority.issue_session(
        SessionIssue(session_id="session-probe-0001", issued_at="2026-08-27T00:00:00Z")
    )
    request = issue_approval_request(
        ApprovalRequestIssue(
            request_id="approval-request-probe-0001",
            session_id="session-probe-0001",
            patch_hash=run.patch_hash,
            simulation_hash=simulation_hash,
            policy_hash=policy.policy_hash,
            requested_at="2026-08-27T00:00:00Z",
            nonce=b"\x09" * 16,
        )
    )
    proof = session.issue_proof(
        ApprovalProofIssue(
            request=request,
            decision=ApprovalDecision.APPROVED,
            proof_id="approval-proof-probe-0001",
            approved_at="2026-08-27T00:00:00Z",
        )
    )
    context = ApprovalValidationContext(
        root=authority.descriptor,
        certificate=session.certificate,
        request=request,
        environment=Environment.TEST,
        trusted_root_hashes=frozenset({authority.descriptor.descriptor_hash}),
        consumed_nonces=frozenset(),
        now=datetime(2026, 8, 27, 0, 0, 30, tzinfo=UTC),
    )
    validate_approval_chain(proof, context)
    machine = ApprovalStateMachine()
    _ = await machine.record_request(request, policy)
    record = await machine.record_proof(proof, context)
    store = DemoSessionStore(signing_key=DEMO_KEY, startup_epoch="epoch-probe-0001")
    created = await store.create_session(
        SessionCreate(session_id="session-probe-0001", now=NOW, nonce=b"\x08" * 16)
    )
    if isinstance(created, SessionCreateDenied):
        raise ProbeInvariantError(ProbeInvariantCode.SESSION_CREATE)
    references = (
        ("scenario-recorded", manifest.manifest_hash),
        ("patch-recorded", run.patch_hash),
        ("simulation-recorded", simulation_hash),
        ("policy-recorded", policy.policy_hash),
        ("approval-recorded", record.proof_hash or "0" * 64),
    )
    for index, (event_type, value) in enumerate(references, start=1):
        result = await store.append_event(
            AppendEventRequest(
                session_id=created.session_id,
                idempotency_key=f"idem-probe-{index:04d}",
                body_hash=f"{index:064x}",
                event=probe_event(index, event_type, value),
            )
        )
        if not isinstance(result, EventAppendAccepted):
            raise ProbeInvariantError(ProbeInvariantCode.EVENT_APPEND)
    race_results: list[EventAppendAccepted] = []

    async def race_append() -> None:
        result = await store.append_event(
            AppendEventRequest(
                session_id=created.session_id,
                idempotency_key="idem-probe-race",
                body_hash="f" * 64,
                event=probe_event(99, "concurrency-recorded", simulation_hash),
            )
        )
        if isinstance(result, EventAppendAccepted):
            race_results.append(result)

    with anyio.fail_after(5):
        async with anyio.create_task_group() as group:
            for _ in range(12):
                _ = group.start_soon(race_append)
    access = await store.access(SessionAccess(token=created.token, now=NOW))
    if not isinstance(access, SessionAccessGranted):
        raise ProbeInvariantError(ProbeInvariantCode.SESSION_ACCESS)
    snapshot_hash = probe_snapshot_hash(access.snapshot.events)
    validate_approval_chain(proof, context)
    unsafe_change = patch.changes[0].model_copy(
        update={"parameters": {"capacity_ues": 1001}}
    )
    unsafe = assess_patch(
        patch.model_copy(update={"changes": (unsafe_change,)}), manifest
    )
    if not isinstance(unsafe, PatchRejected):
        raise ProbeInvariantError(ProbeInvariantCode.UNSAFE_REJECTION)
    stale_input = policy_input.model_copy(
        update={
            "quality": QualityAssessment(
                flags=(ObservationQualityFlag.STALE,), approval_eligible=False
            )
        }
    )
    stale = evaluate_local_policy(stale_input)
    missing_simulation = evaluate_local_policy(
        policy_input.model_copy(
            update={
                "comparison": None,
                "bindings": policy_input.bindings.model_copy(
                    update={"observed_simulation_hash": None}
                ),
            }
        )
    )
    forged_code = "missing"
    try:
        validate_approval_chain(
            proof.model_copy(update={"proof_signature": "A" * 86}), context
        )
    except ContractViolationError as error:
        forged_code = error.code.value
    replay_code = "missing"
    try:
        _ = await machine.record_proof(proof, context)
    except ContractViolationError as error:
        replay_code = error.code.value
    restarted = DemoSessionStore(signing_key=DEMO_KEY, startup_epoch="epoch-probe-0002")
    epoch = await restarted.access(SessionAccess(token=created.token, now=NOW))
    malformed = await store.access(SessionAccess(token="malformed", now=NOW))
    dirty = generate_manifest(91)
    dirty.topology.nodes[0].attributes["capacity_ues"] = 999
    dirty_code = "missing"
    try:
        _ = run_counterfactual(dirty, patch)
    except ManifestIntegrityError:
        dirty_code = "manifest-integrity"
    if not isinstance(epoch, SessionAccessDenied) or not isinstance(
        malformed, SessionAccessDenied
    ):
        raise ProbeInvariantError(ProbeInvariantCode.NEGATIVE_SESSION)
    return ProbeArtifact(
        schema_version="1.0",
        result="pass",
        positive=PositiveEvidence(
            baseline_hash_before=baseline_before,
            baseline_hash_after=run_simulation(manifest).trace_hash,
            candidate_hash=run.candidate_trace.trace_hash,
            comparison_hash=simulation_hash,
            policy_hash=policy.policy_hash,
            certificate_hash=proof.certificate_hash,
            proof_hash=record.proof_hash or "0" * 64,
            evidence_snapshot_hash=snapshot_hash,
            approval_state="approved",
            offline_chain_verified=True,
        ),
        negative=NegativeEvidence(
            replay_code=replay_code,
            epoch_code=epoch.code.value,
            malformed_code=malformed.code.value,
            unsafe_patch_code=unsafe.code.value,
            stale_policy_code=",".join(item.value for item in stale.reasons),
            unsimulated_policy_code=",".join(
                item.value for item in missing_simulation.reasons
            ),
            forged_proof_code=forged_code,
            dirty_baseline_code=dirty_code,
        ),
        concurrency=ConcurrencyEvidence(
            requests=len(race_results),
            original_appends=sum(not item.replayed for item in race_results),
            replays=sum(item.replayed for item in race_results),
            event_count=len(access.snapshot.events),
        ),
        cleanup=CleanupEvidence(
            external_resources_created=False,
            in_memory_only=True,
            cancellation_required=False,
        ),
    )


def main(arguments: list[str]) -> int:
    """Write a complete JSON artifact or return usage failure."""
    if len(arguments) != 2 or arguments[0] != "--out":
        raise ProbeUsageError
    output = Path(arguments[1])
    artifact = anyio.run(_run_probe)
    output.parent.mkdir(parents=True, exist_ok=True)
    _ = output.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
    print(f"task5-probe-pass artifact={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
