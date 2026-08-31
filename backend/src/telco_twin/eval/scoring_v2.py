"""Scoring for the v2 corpus, where abstention is a miss rather than a free pass."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Annotated

from pydantic import Field

from telco_twin.domain._contract import StrictContract
from telco_twin.domain.scenario import FaultFamily
from telco_twin.eval.metrics import ClassMetric
from telco_twin.eval.rules_baseline import DiagnosisPrediction, PredictionStatus

if TYPE_CHECKING:
    from telco_twin.eval.corpus_v2 import CorpusItem
    from telco_twin.eval.rules_baseline import DiagnosisCase

type Predictor = Callable[["DiagnosisCase"], DiagnosisPrediction]


class CorpusMetrics(StrictContract):
    """Per-class and macro scores over a difficulty-tiered corpus."""

    evaluated_count: Annotated[int, Field(ge=1)]
    abstained_count: Annotated[int, Field(ge=0)]
    per_class: Annotated[tuple[ClassMetric, ...], Field(min_length=6, max_length=6)]
    macro_f1: Annotated[float, Field(ge=0, le=1)]


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _f1(precision: float, recall: float) -> float:
    total = precision + recall
    return 2 * precision * recall / total if total else 0.0


def _class_metric(
    label: FaultFamily,
    pairs: tuple[tuple[FaultFamily, FaultFamily | None], ...],
) -> ClassMetric:
    support = sum(expected is label for expected, _ in pairs)
    true_positive = sum(expected is label and predicted is label for expected, predicted in pairs)
    false_positive = sum(
        expected is not label and predicted is label for expected, predicted in pairs
    )
    false_negative = support - true_positive
    precision = _ratio(true_positive, true_positive + false_positive)
    recall = _ratio(true_positive, support)
    return ClassMetric(
        label=label,
        support=support,
        true_positive=true_positive,
        false_positive=false_positive,
        false_negative=false_negative,
        precision=precision,
        recall=recall,
        f1=_f1(precision, recall),
    )


def score_corpus(items: tuple[CorpusItem, ...], predictor: Predictor) -> CorpusMetrics:
    """Score one arm; an abstention is a false negative and never a false positive."""
    predictions = tuple(predictor(item.case) for item in items)
    pairs = tuple(
        (item.case.fault_family, prediction.label)
        for item, prediction in zip(items, predictions, strict=True)
    )
    per_class = tuple(_class_metric(label, pairs) for label in FaultFamily)
    return CorpusMetrics(
        evaluated_count=len(items),
        abstained_count=sum(
            prediction.status is PredictionStatus.ABSTAINED for prediction in predictions
        ),
        per_class=per_class,
        macro_f1=sum(metric.f1 for metric in per_class) / len(per_class),
    )
