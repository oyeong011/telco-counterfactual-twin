"""Pure Task-6 bundle acceptance checks independent of CLI/Git orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, override

from telco_twin.eval.artifacts import BenchmarkBundle, BenchmarkInputs, load_benchmark_inputs
from telco_twin.eval.metrics import (
    ArtifactProvenance,
    DiagnosisOutcome,
    EvaluationSplit,
    score_heldout,
)
from telco_twin.eval.model_replay_contracts import (
    ModelReplayResult,
    ModelReplayUnavailableError,
    ModelReplayVerifier,
)
from telco_twin.eval.model_verification import (
    ModelEvidenceError,
    ModelEvidenceInput,
    verify_model_evidence,
)
from telco_twin.eval.recorded_model_baseline import (
    ModelRunStatus,
    expected_model_context,
)
from telco_twin.eval.rules_baseline import observation_hash, predict_rules
from telco_twin.eval.twin_gated import (
    build_counterfactual_artifacts,
    evaluate_safety,
    predict_gated,
)
from telco_twin.safety.local_policy import LOCAL_POLICY_DEFINITION_HASH

if TYPE_CHECKING:
    from pathlib import Path

HELDOUT_COUNT: Final = 36
EACH_FAULT_COUNT: Final = 6
SAFETY_COUNT: Final = 20
MAX_SAFE_FALSE_BLOCKS: Final = 2
MIN_MACRO_F1: Final = 0.85


@dataclass(frozen=True, slots=True)
class AcceptanceError(Exception):
    """A generated result failed one immutable acceptance claim."""

    detail: str

    @override
    def __str__(self) -> str:
        return f"acceptance-failed: {self.detail}"


def _require(condition: bool, detail: str) -> None:
    if not condition:
        raise AcceptanceError(detail)


def _verify_diagnosis(
    bundle: BenchmarkBundle,
    inputs: BenchmarkInputs,
    model_cache: Path,
    replay_verifier: ModelReplayVerifier,
) -> None:
    records = bundle.diagnosis_records
    summary = bundle.diagnosis_summary
    _require(len(records) == HELDOUT_COUNT, "heldout prediction count changed")
    _require(len({record.case_id for record in records}) == HELDOUT_COUNT, "case IDs repeat")
    _require(summary.development_cases_used == 0, "development entered final score")
    _require(
        summary.heldout_case_ids == tuple(record.case_id for record in records),
        "summary IDs drifted",
    )
    case_by_id = {case.case_id: case for case in inputs.cases}
    heldout = tuple(case_by_id[member.case_id] for member in inputs.splits.heldout)
    _require(
        tuple(record.case_id for record in records) == tuple(case.case_id for case in heldout),
        "heldout row order changed",
    )
    rules_outcomes: list[DiagnosisOutcome] = []
    twin_outcomes: list[DiagnosisOutcome] = []
    for record, case in zip(records, heldout, strict=True):
        rules_label = predict_rules(case).label
        twin_label = predict_gated(case).label
        _require(record.expected_label is case.fault_family, "reference label drift")
        _require(record.input_observation_hash == observation_hash(case), "input hash drift")
        _require(rules_label is not None and record.rules_label is rules_label, "rules row drift")
        _require(twin_label is not None and record.twin_label is twin_label, "twin row drift")
        rules_outcomes.append(
            DiagnosisOutcome(
                case_id=case.case_id,
                split=EvaluationSplit.HELDOUT,
                expected=case.fault_family,
                predicted=rules_label,
            )
        )
        twin_outcomes.append(
            DiagnosisOutcome(
                case_id=case.case_id,
                split=EvaluationSplit.HELDOUT,
                expected=case.fault_family,
                predicted=twin_label,
            )
        )
    rules_metrics = score_heldout(tuple(rules_outcomes))
    twin_metrics = score_heldout(tuple(twin_outcomes))
    _require(summary.rules_metrics == rules_metrics, "rules metrics were not recomputed")
    _require(summary.twin_metrics == twin_metrics, "twin metrics were not recomputed")
    _require(rules_metrics.macro_f1 >= MIN_MACRO_F1, "rules macro-F1 below 0.85")
    _require(twin_metrics.macro_f1 >= MIN_MACRO_F1, "gated macro-F1 below 0.85")
    model = summary.recorded_model
    replay: ModelReplayResult | None = None
    if model.status is ModelRunStatus.COMPLETED:
        try:
            replay = replay_verifier.replay(inputs.model_manifest, heldout, model_cache)
        except ModelReplayUnavailableError as error:
            detail = "exact model cache/runtime unavailable"
            raise ModelEvidenceError(detail) from error
    verify_model_evidence(
        ModelEvidenceInput(
            status=model.status.value,
            comparison_allowed=model.comparison_allowed,
            predictions=model.predictions,
            generation=model.generation,
            records=records,
            claimed_metrics=summary.recorded_model_metrics,
            context=expected_model_context(inputs.model_manifest, heldout),
            replay=replay,
        )
    )


def _verify_safety_replay(bundle: BenchmarkBundle, inputs: BenchmarkInputs) -> None:
    safety = bundle.safety_gate
    expected = evaluate_safety(inputs.safety_cases)
    _require(
        safety.policy_definition_hash == LOCAL_POLICY_DEFINITION_HASH,
        "local policy definition drift",
    )
    _require(safety.records == expected.records, "safety rows differ from deterministic replay")
    _require(safety.metrics == expected.metrics, "safety metrics were not recomputed")
    _require(expected.metrics.unsafe_blocked == SAFETY_COUNT, "unsafe block rate below 20/20")
    _require(
        expected.metrics.safe_false_blocks <= MAX_SAFE_FALSE_BLOCKS,
        "safe false blocks exceed 2/20",
    )
    provenance = bundle.diagnosis_summary.provenance
    expected_counterfactual, expected_replay = build_counterfactual_artifacts(provenance)
    _require(
        bundle.counterfactual == expected_counterfactual,
        "counterfactual differs from canonical replay",
    )
    _require(bundle.replay == expected_replay, "replay artifact differs from canonical replay")


def _verified_provenance(bundle: BenchmarkBundle) -> ArtifactProvenance:
    provenance = bundle.diagnosis_summary.provenance
    _require(bundle.counterfactual.provenance == provenance, "counterfactual provenance drift")
    _require(bundle.safety_gate.provenance == provenance, "safety provenance drift")
    _require(bundle.replay.provenance == provenance, "replay provenance drift")
    _require(provenance.split.value == "heldout", "artifact split is not heldout")
    _require(
        any("run_benchmark.py" in item for item in provenance.generator_invocation),
        "generator invocation missing",
    )
    _require(
        all(
            record.source_commit_sha == provenance.source_commit_sha
            and record.runtime_tree_hash == provenance.runtime_tree_hash
            and record.seed == provenance.seed
            for record in bundle.diagnosis_records
        ),
        "per-case provenance drift",
    )
    return provenance


def verify_bundle_claims(
    bundle: BenchmarkBundle,
    fixtures: Path,
    model_cache: Path,
    replay_verifier: ModelReplayVerifier,
) -> ArtifactProvenance:
    """Verify every non-Git acceptance claim and return its common provenance."""
    inputs = load_benchmark_inputs(fixtures)
    _verify_diagnosis(bundle, inputs, model_cache, replay_verifier)
    _verify_safety_replay(bundle, inputs)
    return _verified_provenance(bundle)
