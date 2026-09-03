"""Task 13: every sized remediation must carry a collateral coupling the bounds cannot see."""

from __future__ import annotations

from telco_twin.domain.intervention import PatchOperation
from telco_twin.eval.safety_corpus_v2 import (
    MODELED_OPERATIONS,
    SafetyTier,
    generate_safety_corpus_v2,
    score_safety_gate,
    tier_value,
    truth_case,
)
from telco_twin.safety.slo_projection import BreachCode, GateKind, decide_patch, project_patch


def test_every_sized_operation_is_modeled_at_every_tier() -> None:
    """Four sized operations times five tiers, each with independent noise draws."""
    corpus = generate_safety_corpus_v2()
    seen = {(item.case.operation, item.tier) for item in corpus}
    assert seen == {(op, tier) for op in MODELED_OPERATIONS for tier in SafetyTier}
    assert len(MODELED_OPERATIONS) == 4


def test_each_operation_has_a_distinct_collateral_breach() -> None:
    """The clear-unsafe tier of each operation must fail on its own coupling, not a shared one."""
    expected = {
        PatchOperation.ADJUST_RADIO_CAPACITY: BreachCode.UPF_CPU_SLO,
        PatchOperation.RESTORE_BACKHAUL_CAPACITY: BreachCode.UPF_CPU_SLO,
        PatchOperation.SCALE_UPF_CAPACITY: BreachCode.SITE_POWER_BUDGET,
        PatchOperation.REBALANCE_SLICE_WEIGHT: BreachCode.PEER_SLICE_LATENCY_SLO,
    }
    for operation, breach in expected.items():
        truth = truth_case(operation, tier_value(operation, SafetyTier.CLEAR_UNSAFE))
        outcome = project_patch(truth)
        assert outcome.fault_cleared, (
            f"{operation.value}: the unsafe patch must still fix the fault"
        )
        assert outcome.breaches == (breach,), f"{operation.value}: {outcome.breaches}"


def test_slice_rebalance_is_zero_sum() -> None:
    """Giving one slice more weight must be what starves its peer, not an unrelated effect."""
    op = PatchOperation.REBALANCE_SLICE_WEIGHT
    safe = project_patch(truth_case(op, tier_value(op, SafetyTier.CLEAR_SAFE)))
    unsafe = project_patch(truth_case(op, tier_value(op, SafetyTier.CLEAR_UNSAFE)))
    peer_safe = dict(safe.projected)["peer_slice_latency_ms"]
    peer_unsafe = dict(unsafe.projected)["peer_slice_latency_ms"]
    assert peer_unsafe > peer_safe


def test_an_ineffective_patch_never_clears_the_fault_in_truth_for_any_operation() -> None:
    for operation in MODELED_OPERATIONS:
        truth = truth_case(operation, tier_value(operation, SafetyTier.INEFFECTIVE))
        assert not project_patch(truth).fault_cleared, operation.value


def test_bounds_gate_still_sees_nothing_across_all_operations() -> None:
    corpus = generate_safety_corpus_v2()
    bounds = score_safety_gate(corpus, GateKind.BOUNDS_ONLY)
    assert bounds.unsafe_denominator >= 32
    assert bounds.unsafe_blocked == 0


def test_projection_gate_separates_without_saturating_per_operation() -> None:
    """Every operation's boundary tiers must leave the gate imperfect in at least one direction."""
    corpus = generate_safety_corpus_v2()
    for operation in MODELED_OPERATIONS:
        subset = tuple(item for item in corpus if item.case.operation is operation)
        metrics = score_safety_gate(subset, GateKind.SLO_PROJECTION)
        assert metrics.unsafe_blocked > 0, operation.value
        imperfect = (
            metrics.unsafe_blocked < metrics.unsafe_denominator or metrics.safe_false_blocks > 0
        )
        assert imperfect, f"{operation.value} is saturated: {metrics}"


def test_decisions_carry_the_projected_metrics_they_were_made_from() -> None:
    corpus = generate_safety_corpus_v2()
    item = next(i for i in corpus if i.tier is SafetyTier.CLEAR_UNSAFE)
    decision = decide_patch(item.case, GateKind.SLO_PROJECTION)
    assert decision.blocked
    assert decision.projected
