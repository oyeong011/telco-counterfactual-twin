"""Task 11: v2 difficulty corpus must separate the rules and twin arms."""

from __future__ import annotations

from telco_twin.domain.scenario import FaultFamily
from telco_twin.eval.corpus_v2 import CorpusItem, DifficultyTier, generate_corpus_v2
from telco_twin.eval.disambiguation import explain_disambiguation, predict_disambiguated
from telco_twin.eval.rules_baseline import PredictionStatus, predict_rules
from telco_twin.eval.scoring_v2 import score_corpus


def test_corpus_v2_is_deterministic_for_one_seed() -> None:
    """Two generations at one seed must be byte-identical."""
    first = generate_corpus_v2(seed=20270827)
    second = generate_corpus_v2(seed=20270827)
    assert [item.case.model_dump_json() for item in first] == [
        item.case.model_dump_json() for item in second
    ]


def test_corpus_v2_covers_every_tier_and_family() -> None:
    """Difficulty tiers and the six families must both be represented."""
    corpus = generate_corpus_v2(seed=20270827)
    assert {item.tier for item in corpus} == set(DifficultyTier)
    assert {item.case.fault_family for item in corpus} == set(FaultFamily)


def test_confounded_cases_defeat_the_rules_baseline_without_noise() -> None:
    """The structural claim: overlapping evidence alone forces the rules to abstain."""
    corpus = generate_corpus_v2(seed=20270827, noise_fraction=0.0)
    confounded = tuple(item for item in corpus if item.tier is DifficultyTier.CONFOUNDED)
    assert confounded
    statuses = {predict_rules(item.case).status for item in confounded}
    assert statuses == {PredictionStatus.ABSTAINED}


def test_measurement_noise_only_ever_helps_the_rules_on_confounded_cases() -> None:
    """Noise can break an overlap, so it must not be sold as making rules weaker."""
    noiseless = generate_corpus_v2(seed=20270827, noise_fraction=0.0)
    noisy = generate_corpus_v2(seed=20270827)

    def resolved(corpus: tuple[CorpusItem, ...]) -> int:
        return sum(
            predict_rules(item.case).status is PredictionStatus.PREDICTED
            for item in corpus
            if item.tier is DifficultyTier.CONFOUNDED
        )

    assert resolved(noisy) >= resolved(noiseless)


def test_twin_resolves_every_confounded_case_without_noise() -> None:
    """Counterfactual disambiguation must recover the dominant primary fault."""
    corpus = generate_corpus_v2(seed=20270827, noise_fraction=0.0)
    confounded = tuple(item for item in corpus if item.tier is DifficultyTier.CONFOUNDED)
    resolved = tuple(predict_disambiguated(item.case) for item in confounded)
    assert all(prediction.status is PredictionStatus.PREDICTED for prediction in resolved)
    assert all(
        prediction.label == item.case.fault_family
        for prediction, item in zip(resolved, confounded, strict=True)
    )


def test_twin_outperforms_rules_on_confounded_cases_under_noise() -> None:
    """Under measurement noise the twin must still beat rules where evidence overlaps."""
    corpus = generate_corpus_v2(seed=20270827)
    confounded = tuple(item for item in corpus if item.tier is DifficultyTier.CONFOUNDED)
    rules_correct = sum(
        predict_rules(item.case).label == item.case.fault_family for item in confounded
    )
    twin_correct = sum(
        predict_disambiguated(item.case).label == item.case.fault_family for item in confounded
    )
    assert twin_correct > rules_correct


def test_twin_macro_f1_exceeds_rules_on_v2_heldout() -> None:
    """The headline claim: the twin arm must beat rules on the held-out split."""
    corpus = generate_corpus_v2(seed=20270827)
    heldout = tuple(item for item in corpus if item.split == "heldout")
    rules = score_corpus(heldout, predict_rules)
    twin = score_corpus(heldout, predict_disambiguated)
    assert rules.macro_f1 < 1.0, "a rules baseline scoring 1.0 means the corpus is still trivial"
    assert twin.macro_f1 > rules.macro_f1


def test_disambiguation_never_invents_a_label_without_simulation() -> None:
    """Every resolved prediction must carry simulator-backed evidence."""
    corpus = generate_corpus_v2(seed=20270827)
    confounded = tuple(item for item in corpus if item.tier is DifficultyTier.CONFOUNDED)
    for item in confounded:
        evidence = explain_disambiguation(item.case)
        assert evidence.simulated_families
        assert evidence.prediction.label in evidence.simulated_families
