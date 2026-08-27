"""C1-local fail-closed policy tests."""

from telco_twin.counterfactual.comparison import (
    CounterfactualComparison,
    compare_counterfactual,
    hash_comparison,
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
    LOCAL_POLICY_DEFINITION_HASH,
    LocalPolicyInput,
    PolicyBindings,
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
    simulation_hash = hash_comparison(comparison)
    return LocalPolicyInput(
        quality=quality or QualityAssessment(flags=(), approval_eligible=True),
        comparison=comparison,
        bindings=PolicyBindings(
            expected_patch_hash=run.patch_hash,
            observed_patch_hash=run.patch_hash,
            expected_simulation_hash=simulation_hash,
            observed_simulation_hash=simulation_hash,
            expected_policy_definition_hash=LOCAL_POLICY_DEFINITION_HASH,
            observed_policy_definition_hash=LOCAL_POLICY_DEFINITION_HASH,
        ),
    )


def test_policy_is_eligible_only_with_fresh_bound_simulation_evidence() -> None:
    # Given: clean quality and exact patch/simulation/policy bindings.
    policy_input = local_policy_input()
    # When: the local policy evaluates the evidence.
    result = evaluate_local_policy(policy_input)
    # Then: eligibility and a stable decision hash are emitted.
    assert result.eligible is True
    assert result.reasons == ()
    assert result.patch_hash == policy_input.bindings.observed_patch_hash
    assert result.simulation_hash == policy_input.bindings.observed_simulation_hash
    assert len(result.policy_hash) == 64


def test_policy_rejects_stale_or_noisy_observation_with_typed_reasons() -> None:
    # Given: explicit stale and noisy quality flags.
    quality = QualityAssessment(
        flags=(ObservationQualityFlag.STALE, ObservationQualityFlag.NOISY),
        approval_eligible=False,
    )
    # When: policy evaluates otherwise valid simulation evidence.
    result = evaluate_local_policy(local_policy_input(quality=quality))
    # Then: both machine-readable quality reasons fail closed.
    assert result.eligible is False
    assert result.reasons == (PolicyReason.OBSERVATION_STALE, PolicyReason.OBSERVATION_NOISY)


def test_policy_rejects_missing_simulator_call() -> None:
    # Given: no comparison and no observed simulation digest.
    policy_input = local_policy_input().model_copy(
        update={
            "comparison": None,
            "bindings": local_policy_input().bindings.model_copy(
                update={"observed_simulation_hash": None}
            ),
        }
    )
    # When: policy evaluates the incomplete evidence.
    result = evaluate_local_policy(policy_input)
    # Then: missing simulation is a stable fail-closed reason.
    assert result.eligible is False
    assert PolicyReason.SIMULATION_MISSING in result.reasons


def test_policy_rejects_missing_or_changed_hash_bindings() -> None:
    # Given: absent patch evidence and changed simulation/policy evidence.
    policy_input = local_policy_input()
    bindings = policy_input.bindings.model_copy(
        update={
            "observed_patch_hash": None,
            "observed_simulation_hash": "0" * 64,
            "observed_policy_definition_hash": "1" * 64,
        }
    )
    # When: policy checks all bindings.
    result = evaluate_local_policy(policy_input.model_copy(update={"bindings": bindings}))
    # Then: every mismatch is explicit and none can be approved.
    assert result.eligible is False
    assert PolicyReason.PATCH_HASH_MISSING in result.reasons
    assert PolicyReason.SIMULATION_HASH_CHANGED in result.reasons
    assert PolicyReason.POLICY_HASH_CHANGED in result.reasons


def test_policy_rejects_failed_counterfactual_constraint() -> None:
    # Given: comparison evidence carrying one explicit failed local constraint.
    policy_input = local_policy_input()
    assert policy_input.comparison is not None
    first_constraint = policy_input.comparison.result.constraints[0].model_copy(
        update={"passed": False}
    )
    result_model = policy_input.comparison.result.model_copy(
        update={
            "constraints": (first_constraint, *policy_input.comparison.result.constraints[1:]),
            "approval_eligible": False,
        }
    )
    comparison = policy_input.comparison.model_copy(update={"result": result_model})
    simulation_hash = hash_comparison(comparison)
    bindings = policy_input.bindings.model_copy(
        update={
            "expected_simulation_hash": simulation_hash,
            "observed_simulation_hash": simulation_hash,
        }
    )
    # When: local policy evaluates the failed constraint.
    result = evaluate_local_policy(
        policy_input.model_copy(update={"comparison": comparison, "bindings": bindings})
    )
    # Then: unsafe typed evidence is never approval eligible.
    assert result.eligible is False
    assert result.reasons == (PolicyReason.UNSAFE_CONSTRAINT,)


def test_alarm_prose_is_not_a_policy_input() -> None:
    # Given: the machine-consumed local policy input model.
    field_names = frozenset(LocalPolicyInput.model_fields)
    # When: its accepted boundary is inspected.
    prose_fields = field_names & {"alarm", "alarm_message", "message", "prompt", "text"}
    # Then: untrusted alarm prose has no route into policy.
    assert prose_fields == frozenset()
