"""Generate the v2 difficulty benchmark artifact.

Every number the README or a report may quote about arm separation must come from
this generator, carrying the seed, the noise setting, and the source commit.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import cast

from telco_twin.eval.corpus_v2 import (
    NOISE_FRACTION,
    CorpusItem,
    DifficultyTier,
    generate_corpus_v2,
)
from telco_twin.eval.disambiguation import predict_disambiguated
from telco_twin.eval.rules_baseline import predict_rules
from telco_twin.eval.safety_corpus_v2 import (
    MODELED_OPERATIONS,
    SafetyGateMetrics,
    SafetyTier,
    generate_safety_corpus_v2,
    score_safety_gate,
)
from telco_twin.eval.scoring_v2 import CorpusMetrics, Predictor, score_corpus
from telco_twin.safety.slo_projection import GateKind

DEFAULT_SEED = 20270827


def _source_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        check=True,
        text=True,
    )
    return result.stdout.strip()


def _tier_breakdown(
    items: tuple[CorpusItem, ...], predictor: Predictor
) -> dict[str, dict[str, int]]:
    breakdown: dict[str, dict[str, int]] = {}
    for tier in DifficultyTier:
        tier_items = tuple(item for item in items if item.tier is tier)
        correct = sum(
            predictor(item.case).label == item.case.fault_family for item in tier_items
        )
        breakdown[tier.value] = {"cases": len(tier_items), "correct": correct}
    return breakdown


def _metrics_payload(metrics: CorpusMetrics) -> dict[str, object]:
    return {
        "evaluated_count": metrics.evaluated_count,
        "abstained_count": metrics.abstained_count,
        "macro_f1": metrics.macro_f1,
        "per_class": [
            {"label": item.label.value, "support": item.support, "f1": item.f1}
            for item in metrics.per_class
        ],
    }


def _gate_counts(metrics: SafetyGateMetrics) -> dict[str, int]:
    return {
        "unsafe_blocked": metrics.unsafe_blocked,
        "unsafe_denominator": metrics.unsafe_denominator,
        "safe_false_blocks": metrics.safe_false_blocks,
        "safe_denominator": metrics.safe_denominator,
    }


def _safety_payload() -> dict[str, object]:
    corpus = generate_safety_corpus_v2()
    scored = {gate: score_safety_gate(corpus, gate) for gate in GateKind}
    gates = {gate.value: _gate_counts(metrics) for gate, metrics in scored.items()}
    per_operation = {
        operation.value: {
            gate.value: _gate_counts(
                score_safety_gate(
                    tuple(item for item in corpus if item.case.operation is operation),
                    gate,
                )
            )
            for gate in GateKind
        }
        for operation in MODELED_OPERATIONS
    }
    return {
        "corpus_total": len(corpus),
        "tiers": [tier.value for tier in SafetyTier],
        "operations": [operation.value for operation in MODELED_OPERATIONS],
        "gates": gates,
        "per_operation": per_operation,
        "bounds_gate_blind_spot": (
            "The shipped bounds-only checks block none of the unsafe cases, because "
            "every one of them satisfies the parameter range, the blast radius, and "
            "every integrity hash while still breaching an unrelated SLO."
        ),
    }


def main() -> int:
    """Score both arms on the held-out v2 split and write one JSON artifact."""
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    _ = parser.add_argument(
        "--out", type=Path, default=Path("artifacts/eval-v2/diagnosis-v2.json")
    )
    namespace = parser.parse_args()
    seed = cast("int", namespace.seed)
    out = cast("Path", namespace.out)

    corpus = generate_corpus_v2(seed=seed)
    heldout = tuple(item for item in corpus if item.split.value == "heldout")
    rules = score_corpus(heldout, predict_rules)
    twin = score_corpus(heldout, predict_disambiguated)
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "provenance": {
            "source_commit_sha": _source_commit(),
            "generator_invocation": [
                "python",
                "scripts/run_benchmark_v2.py",
                "--seed",
                str(seed),
            ],
            "seed": seed,
            "split": "heldout",
            "corpus_total": len(corpus),
            "noise_fraction": NOISE_FRACTION,
        },
        "arms": {
            "rules_only": _metrics_payload(rules),
            "twin_disambiguated": _metrics_payload(twin),
        },
        "tier_breakdown": {
            "rules_only": _tier_breakdown(heldout, predict_rules),
            "twin_disambiguated": _tier_breakdown(heldout, predict_disambiguated),
        },
        "separation": {
            "macro_f1_delta": twin.macro_f1 - rules.macro_f1,
            "twin_beats_rules": twin.macro_f1 > rules.macro_f1,
            "neither_arm_is_saturated": rules.macro_f1 < 1.0 and twin.macro_f1 < 1.0,
        },
        "safety": _safety_payload(),
        "limitations": [
            (
                "The twin inverts the same forward model that generated each case; "
                "measurement noise is the only source of model mismatch."
            ),
            "All data is synthetic. No operator network, traffic, or customer data is used.",
            "Severity levels are a discrete table, not a continuous physical model.",
            (
                "Each safety projection models one collateral coupling per operation: "
                "radio and backhaul capacity load the core, UPF units draw site power, "
                "slice weight starves the peer slice. Real remediation has many more."
            ),
        ],
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    _ = out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
