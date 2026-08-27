"""C1-local fail-closed policy tests."""

from dataclasses import fields

from telco_twin.counterfactual.comparison import (
    CounterfactualComparison,
    compare_counterfactual,
)
from telco_twin.counterfactual.runner import CounterfactualRun, run_counterfactual
from telco_twin.data.synthetic import generate_manifest
from telco_twin.domain.intervention import (
    BlastRadius,
    PatchChange,
    PatchOperation,
    TargetKind,
    TypedPatch,
)
from telco_twin.safety.local_policy import (
    QUALITY_REASONS,
    LocalPolicyInput,
    PolicyDecision,
    PolicyReason,
    evaluate_local_policy,
)
from telco_twin.simulator.metrics import ObservationQualityFlag, QualityAssessment


def _comparison() -> tuple[CounterfactualRun, CounterfactualComparison]:
    manifest = generate_manifest(67)
    patch = TypedPatch(
        patch_id="patch-0001",
        scenario_id=manifest.scenario.scenario_id,
        base_topology_hash=manifest.topology_hash,
        changes=(
            PatchChange(
                target_id="cell-0001",
                target_kind=TargetKind.CELL,
                operation=PatchOperation.ADJUST_RADIO_CAPACITY,
                parameters={"capacity_ues": 230},
            ),
        ),
        blast_radius=BlastRadius(max_cells=1, max_ue_cohorts=1, max_slices=1),
        proposed_at="2026-08-27T00:00:00Z",
        schema_version="1.0",
    )
    run = run_counterfactual(manifest, patch)
    assert isinstance(run, CounterfactualRun)
    return run, compare_counterfactual(run, "simulation-0001")


def local_policy_input(*, quality: QualityAssessment | None = None) -> LocalPolicyInput:
    run, comparison = _comparison()
    return LocalPolicyInput(
        quality=quality or QualityAssessment(flags=(), approval_eligible=True),
        run=run,
        comparison=comparison,
    )


def real_policy_decision(*, quality: QualityAssessment | None = None) -> PolicyDecision:
    """Return policy provenance backed by a real deterministic run/comparison."""
    return evaluate_local_policy(local_policy_input(quality=quality))


def test_policy_is_eligible_only_with_fresh_recomputed_simulation_evidence() -> None:
    # Given: clean quality and an actual deterministic run/comparison.
    decision = real_policy_decision()
    # When: the local policy evaluates and seals provenance.
    result = decision.evidence
    # Then: serializable evidence is eligible but distinct from the capability.
    assert result.eligible is True
    assert result.reasons == ()
    assert result.patch_hash is not None
    assert result.simulation_hash is not None
    assert len(result.policy_hash) == 64


def test_policy_rejects_stale_or_noisy_observation_with_typed_reasons() -> None:
    # Given: explicit stale and noisy quality flags.
    quality = QualityAssessment(
        flags=(ObservationQualityFlag.STALE, ObservationQualityFlag.NOISY),
        approval_eligible=False,
    )
    # When: policy evaluates otherwise valid simulator provenance.
    result = real_policy_decision(quality=quality).evidence
    # Then: both machine-readable quality reasons fail closed.
    assert result.eligible is False
    assert result.reasons == (PolicyReason.OBSERVATION_STALE, PolicyReason.OBSERVATION_NOISY)


def test_policy_rejects_missing_simulator_call() -> None:
    # Given: no run and no comparison capability.
    policy_input = LocalPolicyInput(
        quality=QualityAssessment(flags=(), approval_eligible=True),
        run=None,
        comparison=None,
    )
    # When: policy evaluates the incomplete evidence.
    result = evaluate_local_policy(policy_input).evidence
    # Then: missing simulator provenance is explicit and ineligible.
    assert result.eligible is False
    assert result.reasons == (
        PolicyReason.PATCH_HASH_MISSING,
        PolicyReason.SIMULATION_HASH_MISSING,
        PolicyReason.SIMULATION_MISSING,
    )


def test_policy_rejects_changed_constraint_comparison_as_invalid_provenance() -> None:
    # Given: one comparison whose constraint was changed after simulation.
    policy_input = local_policy_input()
    assert policy_input.comparison is not None
    first = policy_input.comparison.result.constraints[0]
    result = policy_input.comparison.result.model_copy(
        update={
            "constraints": (
                first.model_copy(update={"passed": False}),
                *policy_input.comparison.result.constraints[1:],
            ),
            "approval_eligible": False,
        }
    )
    comparison = policy_input.comparison.model_copy(update={"result": result})
    # When: local policy recomputes the simulator-owned comparison.
    decision = evaluate_local_policy(
        LocalPolicyInput(
            quality=policy_input.quality,
            run=policy_input.run,
            comparison=comparison,
        )
    )
    # Then: caller-mutated constraints cannot become policy provenance.
    assert decision.evidence.eligible is False
    assert decision.evidence.reasons == (PolicyReason.SIMULATION_PROVENANCE_INVALID,)


def test_alarm_prose_is_not_a_policy_input() -> None:
    # Given: the internal machine-consumed policy input dataclass.
    field_names = frozenset(field.name for field in fields(LocalPolicyInput))
    # When: its accepted boundary is inspected.
    prose_fields = field_names & {"alarm", "alarm_message", "message", "prompt", "text"}
    # Then: untrusted alarm prose has no route into policy.
    assert prose_fields == frozenset()


def test_every_observation_quality_flag_has_one_policy_reason() -> None:
    # Given/When/Then: the immutable reason map remains exhaustive as flags evolve.
    assert frozenset(QUALITY_REASONS) == frozenset(ObservationQualityFlag)
