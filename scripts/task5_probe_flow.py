"""Real Task5 lifecycle and adversarial probe flow."""

from __future__ import annotations

from datetime import UTC, datetime

from telco_twin.approval.authority import (
    ApprovalProofIssue,
    ApprovalRequestIssue,
    AuthorityMode,
    SessionIssue,
    issue_approval_request,
    load_approval_authority,
)
from telco_twin.approval.state_machine import ApprovalStateMachine
from telco_twin.approval.trust import ApprovalTrustConfig
from telco_twin.counterfactual.comparison import compare_counterfactual, hash_comparison
from telco_twin.counterfactual.runner import CounterfactualRun, run_counterfactual
from telco_twin.data.synthetic import generate_manifest
from telco_twin.domain.approval import (
    ApprovalDecision,
    ApprovalValidationContext,
    Environment,
    validate_approval_chain,
)
from telco_twin.safety.local_policy import evaluate_local_policy
from telco_twin.simulator.engine import run_simulation
from telco_twin.state.memory_store import DemoSessionStore
from telco_twin.state.probe_evidence import (
    ConcurrencyEvidence,
    PositiveEvidence,
    ProbeArtifact,
)
from telco_twin.state.store_models import (
    AppendEventRequest,
    EventAppendAccepted,
    SessionAccess,
    SessionAccessGranted,
    SessionCreate,
    SessionCreateDenied,
)
from telco_twin.state.trusted_clock import FixedClock

from scripts.task5_probe_artifact import ProbeArtifactParts, assemble_probe_artifact
from scripts.task5_probe_flow_types import (
    ApprovalNegativeInputs,
    ProbeNegativeInputs,
    ScenarioNegativeInputs,
    StoreNegativeInputs,
)
from scripts.task5_probe_negatives import collect_negative_evidence
from scripts.task5_probe_support import (
    DEMO_KEY,
    ProbeInvariantCode,
    ProbeInvariantError,
    probe_event,
    probe_idempotency_race,
    probe_patch,
    probe_policy_input,
    probe_snapshot_hash,
    require_proof_hash,
)

PROBE_TIME = datetime(2026, 8, 27, 0, 0, 30, tzinfo=UTC)
STALE_TIME = datetime(2026, 8, 27, 0, 5, 0, tzinfo=UTC)


async def run_probe() -> ProbeArtifact:
    """Run positive evidence flow and every required stable negative."""
    clock = FixedClock(PROBE_TIME)
    manifest = generate_manifest(91)
    patch = probe_patch()
    baseline_before = run_simulation(manifest).trace_hash
    run = run_counterfactual(manifest, patch)
    if not isinstance(run, CounterfactualRun):
        raise ProbeInvariantError(ProbeInvariantCode.COUNTERFACTUAL)
    comparison = compare_counterfactual(run, "simulation-probe-0001")
    simulation_hash = hash_comparison(comparison)
    policy_input = probe_policy_input(run, comparison)
    policy = evaluate_local_policy(policy_input, clock)
    policy_evidence = policy.evidence
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
            policy_hash=policy_evidence.policy_hash,
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
        now=PROBE_TIME,
    )
    validate_approval_chain(proof, context)
    trust = ApprovalTrustConfig(
        environment=Environment.TEST,
        root=authority.descriptor,
        trusted_root_hashes=frozenset({authority.descriptor.descriptor_hash}),
    )
    machine = ApprovalStateMachine(trust, clock)
    _ = await machine.record_request(request, policy, session.certificate)
    record = await machine.record_proof(proof)
    recorded_proof_hash = require_proof_hash(record.proof_hash)
    store = DemoSessionStore(
        signing_key=DEMO_KEY,
        startup_epoch="epoch-probe-0001",
        clock=clock,
    )
    created = await store.create_session(
        SessionCreate(session_id="session-probe-0001", nonce=b"\x08" * 16)
    )
    if isinstance(created, SessionCreateDenied):
        raise ProbeInvariantError(ProbeInvariantCode.SESSION_CREATE)
    references = (
        ("scenario-recorded", manifest.manifest_hash),
        ("patch-recorded", run.patch_hash),
        ("simulation-recorded", simulation_hash),
        ("policy-recorded", policy_evidence.policy_hash),
        ("approval-recorded", recorded_proof_hash),
    )
    for index, (event_type, value) in enumerate(references, start=1):
        result = await store.append_event(
            AppendEventRequest(
                token=created.token,
                idempotency_key=f"idem-probe-{index:04d}",
                event=probe_event(index, event_type, value),
            )
        )
        if not isinstance(result, EventAppendAccepted):
            raise ProbeInvariantError(ProbeInvariantCode.EVENT_APPEND)
    race_results = await probe_idempotency_race(
        store,
        created.token,
        simulation_hash,
    )
    access = await store.access(SessionAccess(token=created.token))
    if not isinstance(access, SessionAccessGranted):
        raise ProbeInvariantError(ProbeInvariantCode.SESSION_ACCESS)
    snapshot_hash = probe_snapshot_hash(access.snapshot.events)
    negative = await collect_negative_evidence(
        ProbeNegativeInputs(
            approval=ApprovalNegativeInputs(
                proof=proof,
                context=context,
                authority=authority,
                machine=machine,
            ),
            store=StoreNegativeInputs(
                store=store,
                token=created.token,
                clock=clock,
            ),
            scenario=ScenarioNegativeInputs(
                manifest=manifest,
                patch=patch,
                policy_input=policy_input,
                stale_time=STALE_TIME,
            ),
        )
    )
    return assemble_probe_artifact(
        ProbeArtifactParts(
            manifest=manifest,
            observation=policy_input.observation,
            patch_hash=run.patch_hash,
            positive=PositiveEvidence(
                baseline_hash_before=baseline_before,
                baseline_hash_after=run_simulation(manifest).trace_hash,
                candidate_hash=run.candidate_trace.trace_hash,
                comparison_hash=simulation_hash,
                policy_hash=policy_evidence.policy_hash,
                certificate_hash=proof.certificate_hash,
                proof_hash=recorded_proof_hash,
                evidence_snapshot_hash=snapshot_hash,
                approval_state="approved",
                offline_chain_verified=True,
            ),
            negative=negative,
            concurrency=ConcurrencyEvidence(
                requests=len(race_results),
                original_appends=sum(not item.replayed for item in race_results),
                replays=sum(item.replayed for item in race_results),
                event_count=len(access.snapshot.events),
            ),
        )
    )
