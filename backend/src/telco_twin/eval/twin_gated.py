"""Quality-gated diagnosis and real simulator-backed safety adapter."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

from telco_twin.counterfactual.comparison import compare_counterfactual, hash_comparison
from telco_twin.counterfactual.runner import (
    CounterfactualRejected,
    CounterfactualRun,
    run_counterfactual,
)
from telco_twin.data.synthetic import SimulationManifest, generate_manifest
from telco_twin.domain.intervention import (
    BlastRadius,
    PatchChange,
    PatchOperation,
    TargetKind,
    TypedPatch,
)
from telco_twin.eval.metrics import (
    ArtifactGenerationError,
    ArtifactProvenance,
    CounterfactualArtifact,
    ReplayArtifact,
    SafetyExpectation,
    SafetyRecord,
    safety_outcome,
    score_safety,
)
from telco_twin.eval.rules_baseline import (
    DiagnosisCase,
    DiagnosisPrediction,
    PredictionStatus,
    SafetyCase,
    SafetyEvaluation,
    SafetyMode,
    predict_rules,
)
from telco_twin.safety.local_policy import LocalPolicyInput, evaluate_local_policy
from telco_twin.simulator.metric_values import MetricWindow
from telco_twin.simulator.metrics import QualityContext, QualityPolicy, assess_observation_quality
from telco_twin.simulator.network_model import ConfigSnapshot, NetworkObservation
from telco_twin.state.trusted_clock import FixedClock

OBSERVED_AT: Final = "2026-08-27T00:00:30Z"
FRESH_TIME: Final = datetime(2026, 8, 27, 0, 1, 0, tzinfo=UTC)
STALE_TIME: Final = datetime(2026, 8, 27, 0, 5, 0, tzinfo=UTC)


def predict_gated(case: DiagnosisCase) -> DiagnosisPrediction:
    """Require clean typed observation quality before diagnosing."""
    quality = assess_observation_quality(
        case.observation,
        QualityContext(assessed_at=case.assessed_at),
    )
    if not quality.approval_eligible:
        return DiagnosisPrediction(
            case_id=case.case_id,
            status=PredictionStatus.ABSTAINED,
            label=None,
            quality_flags=quality.flags,
            schema_version="1.0",
        )
    return predict_rules(case)


def _patch(case: SafetyCase, manifest: SimulationManifest) -> TypedPatch:
    return TypedPatch(
        patch_id=f"patch-{case.case_id}",
        scenario_id=manifest.scenario.scenario_id,
        base_topology_hash=manifest.topology_hash,
        changes=(
            PatchChange(
                target_id="cell-0001",
                target_kind=TargetKind.CELL,
                operation=PatchOperation.ADJUST_RADIO_CAPACITY,
                parameters={"capacity_ues": case.capacity_ues},
            ),
        ),
        blast_radius=BlastRadius(max_cells=1, max_ue_cohorts=1, max_slices=0),
        proposed_at="2026-08-27T00:00:00Z",
        schema_version="1.0",
    )


def _observation(manifest: SimulationManifest, *, binding_mismatch: bool) -> NetworkObservation:
    scenario_id = "scenario-binding-mismatch" if binding_mismatch else manifest.scenario.scenario_id
    window = MetricWindow(
        target_id="cell-0001",
        observed_at=OBSERVED_AT,
        prb_utilization_pct=55.0,
        sinr_db=18.0,
        rsrp_dbm=-85.0,
        rsrq_db=-10.0,
        throughput_mbps=800.0,
        latency_ms=20.0,
        packet_loss_pct=0.1,
        handover_attempts=100,
        handover_failures=2,
        active_ues=120,
        slice_slo_throughput_mbps=200.0,
        slice_throughput_mbps=240.0,
        slice_slo_latency_ms=50.0,
        slice_latency_ms=25.0,
        nf_cpu_utilization_pct=45.0,
    )
    config = ConfigSnapshot(
        config_version="config-safety-v1",
        target_id="cell-0001",
        recorded_at="2026-08-27T00:00:00Z",
        neighbor_relation_valid=True,
        slice_scheduler_share_pct=40.0,
        expected_slice_share_pct=40.0,
    )
    return NetworkObservation(
        scenario_id=scenario_id,
        topology_id=manifest.topology.topology_id,
        windows=(window,),
        alarms=(),
        config_history=(config,),
    )


def _policy_record(
    case: SafetyCase,
    run: CounterfactualRun,
    *,
    stale: bool,
    binding_mismatch: bool,
    tampered: bool,
) -> SafetyRecord:
    comparison = compare_counterfactual(run, f"simulation-{case.case_id}")
    if tampered:
        first = comparison.result.constraints[0]
        result = comparison.result.model_copy(
            update={
                "constraints": (
                    first.model_copy(update={"passed": False}),
                    *comparison.result.constraints[1:],
                ),
                "approval_eligible": False,
            }
        )
        comparison = comparison.model_copy(update={"result": result})
    decision = evaluate_local_policy(
        LocalPolicyInput(
            observation=_observation(
                manifest=run.baseline_manifest, binding_mismatch=binding_mismatch
            ),
            quality_policy=QualityPolicy(),
            run=run,
            comparison=comparison,
        ),
        FixedClock(STALE_TIME if stale else FRESH_TIME),
    )
    return SafetyRecord(
        case_id=case.case_id,
        expected_unsafe=case.expectation is SafetyExpectation.UNSAFE,
        blocked=not decision.evidence.eligible,
        simulator_called=True,
        reasons=tuple(reason.value for reason in decision.evidence.reasons),
        trace_hash=run.candidate_trace.trace_hash,
        schema_version="1.0",
    )


def evaluate_safety_case(case: SafetyCase) -> SafetyRecord:
    """Traverse production patch, simulator, comparison, and local-policy seams."""
    manifest = generate_manifest(case.seed)
    match case.mode:  # noqa: MATCH_OK - exhaustive enum; default is statically unreachable
        case SafetyMode.MISSING_SIMULATION:
            decision = evaluate_local_policy(
                LocalPolicyInput(
                    observation=_observation(manifest, binding_mismatch=False),
                    quality_policy=QualityPolicy(),
                    run=None,
                    comparison=None,
                ),
                FixedClock(FRESH_TIME),
            )
            return SafetyRecord(
                case_id=case.case_id,
                expected_unsafe=True,
                blocked=True,
                simulator_called=False,
                reasons=tuple(reason.value for reason in decision.evidence.reasons),
                trace_hash=None,
                schema_version="1.0",
            )
        case (
            SafetyMode.SAFE
            | SafetyMode.PATCH_OUT_OF_RANGE
            | SafetyMode.STALE_OBSERVATION
            | SafetyMode.BINDING_MISMATCH
            | SafetyMode.TAMPERED_COMPARISON
        ):
            outcome = run_counterfactual(manifest, _patch(case, manifest))
    match outcome:  # noqa: MATCH_OK - exhaustive union; default is statically unreachable
        case CounterfactualRejected(assessment=assessment):
            return SafetyRecord(
                case_id=case.case_id,
                expected_unsafe=True,
                blocked=True,
                simulator_called=False,
                reasons=(assessment.code.value,),
                trace_hash=None,
                schema_version="1.0",
            )
        case CounterfactualRun():
            return _policy_record(
                case,
                outcome,
                stale=case.mode is SafetyMode.STALE_OBSERVATION,
                binding_mismatch=case.mode is SafetyMode.BINDING_MISMATCH,
                tampered=case.mode is SafetyMode.TAMPERED_COMPARISON,
            )


def evaluate_safety(cases: tuple[SafetyCase, ...]) -> SafetyEvaluation:
    """Run every frozen safety case through production adapters."""
    records = tuple(evaluate_safety_case(case) for case in cases)
    return SafetyEvaluation(
        records=records,
        metrics=score_safety(tuple(safety_outcome(record) for record in records)),
    )


def build_counterfactual_artifacts(
    provenance: ArtifactProvenance,
) -> tuple[CounterfactualArtifact, ReplayArtifact]:
    """Run one real deterministic benchmark counterfactual and replay."""
    case = SafetyCase(
        case_id="benchmark-v1",
        expectation=SafetyExpectation.SAFE,
        mode=SafetyMode.SAFE,
        seed=provenance.seed,
        capacity_ues=250,
        schema_version="1.0",
    )
    manifest = generate_manifest(case.seed)
    outcome = run_counterfactual(manifest, _patch(case, manifest))
    match outcome:  # noqa: MATCH_OK - exhaustive union; default is statically unreachable
        case CounterfactualRejected(assessment=assessment):
            raise ArtifactGenerationError(assessment.code.value)
        case CounterfactualRun():
            comparison = compare_counterfactual(outcome, "simulation-benchmark-v1")
    counterfactual = CounterfactualArtifact(
        provenance=provenance,
        simulator_called=True,
        baseline_unchanged=outcome.baseline_state_hash_before == outcome.baseline_state_hash_after,
        patch_hash=outcome.patch_hash,
        baseline_trace_hash=outcome.baseline_trace.trace_hash,
        candidate_trace_hash=outcome.candidate_trace.trace_hash,
        replay_trace_hash=outcome.replay_trace.trace_hash,
        comparison_hash=hash_comparison(comparison),
        schema_version="1.0",
    )
    replay = ReplayArtifact(
        provenance=provenance,
        candidate_trace_hash=outcome.candidate_trace.trace_hash,
        replay_trace_hash=outcome.replay_trace.trace_hash,
        deterministic=outcome.candidate_trace.trace_hash == outcome.replay_trace.trace_hash,
        external_effects="none-synthetic",
        schema_version="1.0",
    )
    return counterfactual, replay
