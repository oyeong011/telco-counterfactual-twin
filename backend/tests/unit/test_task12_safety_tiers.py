"""Task 12: the safety axis must measure judgment, not restate binary bounds."""

from __future__ import annotations

from telco_twin.domain.intervention import PatchOperation
from telco_twin.eval.safety_corpus_v2 import (
    SafetyTier,
    generate_safety_corpus_v2,
    score_safety_gate,
    tier_value,
    truth_case,
)
from telco_twin.safety.slo_projection import GateKind, decide_patch, project_patch


def test_safety_corpus_v2_covers_every_tier() -> None:
    """Boundary tiers must exist on both sides of the SLO edge."""
    corpus = generate_safety_corpus_v2()
    assert {item.tier for item in corpus} == set(SafetyTier)


def test_bounds_only_gate_approves_every_case_including_the_unsafe_ones() -> None:
    """The current production checks are blind to collateral SLO damage."""
    corpus = generate_safety_corpus_v2()
    unsafe = tuple(item for item in corpus if item.expected_unsafe)
    assert unsafe
    blocked = sum(decide_patch(item.case, GateKind.BOUNDS_ONLY).blocked for item in unsafe)
    assert blocked == 0


def test_projection_gate_blocks_the_unsafe_cases_the_bounds_gate_misses() -> None:
    """Projecting the patched observation must recover the missed blocks."""
    corpus = generate_safety_corpus_v2()
    bounds = score_safety_gate(corpus, GateKind.BOUNDS_ONLY)
    projection = score_safety_gate(corpus, GateKind.SLO_PROJECTION)
    assert projection.unsafe_blocked > bounds.unsafe_blocked


def test_neither_safety_gate_is_saturated_on_the_tiered_corpus() -> None:
    """A gate scoring a perfect sweep would mean the corpus carries no difficulty."""
    corpus = generate_safety_corpus_v2()
    projection = score_safety_gate(corpus, GateKind.SLO_PROJECTION)
    assert projection.unsafe_denominator > 0
    assert projection.unsafe_blocked < projection.unsafe_denominator


def test_an_ineffective_patch_does_not_clear_the_fault_in_truth() -> None:
    """A patch too small to relieve the cell must not read as a successful change."""
    radio = PatchOperation.ADJUST_RADIO_CAPACITY
    truth = truth_case(radio, tier_value(radio, SafetyTier.INEFFECTIVE))
    assert not project_patch(truth).fault_cleared


def test_measurement_noise_leaves_the_ineffective_tier_genuinely_undecided() -> None:
    """The gate sees only a noisy cell, so it cannot settle this tier either way."""
    corpus = generate_safety_corpus_v2()
    ineffective = tuple(item for item in corpus if item.tier is SafetyTier.INEFFECTIVE)
    cleared = sum(
        decide_patch(item.case, GateKind.SLO_PROJECTION).fault_cleared for item in ineffective
    )
    assert 0 < cleared < len(ineffective)


def test_the_bounds_gate_blind_spot_is_total_not_partial() -> None:
    """Record the size of the gap the projection gate exists to close."""
    corpus = generate_safety_corpus_v2()
    bounds = score_safety_gate(corpus, GateKind.BOUNDS_ONLY)
    assert bounds.unsafe_denominator > 0
    assert bounds.unsafe_blocked == 0
    assert bounds.safe_false_blocks == 0
