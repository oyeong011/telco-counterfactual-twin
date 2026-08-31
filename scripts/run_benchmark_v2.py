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
from typing import Any

from telco_twin.eval.corpus_v2 import NOISE_FRACTION, DifficultyTier, generate_corpus_v2
from telco_twin.eval.disambiguation import predict_disambiguated
from telco_twin.eval.rules_baseline import predict_rules
from telco_twin.eval.scoring_v2 import CorpusMetrics, Predictor, score_corpus

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
    items: tuple[Any, ...], predictor: Predictor
) -> dict[str, dict[str, int]]:
    breakdown: dict[str, dict[str, int]] = {}
    for tier in DifficultyTier:
        tier_items = tuple(item for item in items if item.tier is tier)
        correct = sum(
            predictor(item.case).label == item.case.fault_family for item in tier_items
        )
        breakdown[tier.value] = {"cases": len(tier_items), "correct": correct}
    return breakdown


def _metrics_payload(metrics: CorpusMetrics) -> dict[str, Any]:
    return {
        "evaluated_count": metrics.evaluated_count,
        "abstained_count": metrics.abstained_count,
        "macro_f1": metrics.macro_f1,
        "per_class": [
            {"label": item.label.value, "support": item.support, "f1": item.f1}
            for item in metrics.per_class
        ],
    }


def main() -> int:
    """Score both arms on the held-out v2 split and write one JSON artifact."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--out", type=Path, default=Path("artifacts/eval/diagnosis-v2.json")
    )
    args = parser.parse_args()

    corpus = generate_corpus_v2(seed=args.seed)
    heldout = tuple(item for item in corpus if item.split.value == "heldout")
    rules = score_corpus(heldout, predict_rules)
    twin = score_corpus(heldout, predict_disambiguated)
    payload = {
        "schema_version": "1.0",
        "provenance": {
            "source_commit_sha": _source_commit(),
            "generator_invocation": [
                "python",
                "scripts/run_benchmark_v2.py",
                "--seed",
                str(args.seed),
            ],
            "seed": args.seed,
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
        "limitations": [
            (
                "The twin inverts the same forward model that generated each case; "
                "measurement noise is the only source of model mismatch."
            ),
            "All data is synthetic. No operator network, traffic, or customer data is used.",
            "Severity levels are a discrete table, not a continuous physical model.",
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
