"""Content-verifiable recorded-model outputs and generation provenance."""

from __future__ import annotations

import hashlib
from typing import Annotated, Self

from pydantic import Field, model_validator

from telco_twin.domain._contract import ContractId, Sha256Hex, StrictContract
from telco_twin.domain._validation import fail_validation
from telco_twin.domain.scenario import FaultFamily  # noqa: TC001
from telco_twin.eval.model_input import fault_from_code


def _hash_fields(values: tuple[str, ...]) -> Sha256Hex:
    digest = hashlib.sha256()
    for value in values:
        encoded = value.encode()
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _parsed_label(raw: str) -> FaultFamily | None:
    return fault_from_code(raw)


class ModelCaseBinding(StrictContract):
    """Current held-out input identities needed to verify one prediction."""

    case_id: ContractId
    expected_label: FaultFamily
    observation_hash: Sha256Hex
    prompt_hash: Sha256Hex


def _case_hash(case: ModelCaseBinding) -> Sha256Hex:
    return _hash_fields((case.case_id, case.observation_hash, case.prompt_hash))


class ModelEvidenceContext(StrictContract):
    """Exact model manifest and ordered held-out inputs used for generation."""

    model_manifest_hash: Sha256Hex
    input_set_hash: Sha256Hex
    cases: Annotated[tuple[ModelCaseBinding, ...], Field(min_length=36, max_length=36)]

    @model_validator(mode="after")
    def input_hash_is_bound(self) -> Self:
        """Reject duplicated cases or an altered ordered input-set identity."""
        if len({case.case_id for case in self.cases}) != len(self.cases):
            fail_validation("model_case_duplicate", "model case identifiers repeat")
        if self.input_set_hash != _hash_fields(tuple(_case_hash(case) for case in self.cases)):
            fail_validation("model_input_hash", "model input-set hash mismatch")
        return self


class RecordedModelPrediction(StrictContract):
    """Raw model text plus every case/input/prediction content binding."""

    case_id: ContractId
    label: FaultFamily | None
    observation_hash: Sha256Hex
    prompt_hash: Sha256Hex
    raw_output: Annotated[str, Field(min_length=1, max_length=4096)]
    raw_output_hash: Sha256Hex
    prediction_hash: Sha256Hex

    @model_validator(mode="after")
    def raw_output_is_bound(self) -> Self:
        """Recompute raw bytes, parsed label, and complete prediction identity."""
        raw_hash = hashlib.sha256(self.raw_output.encode()).hexdigest()
        label = _parsed_label(self.raw_output)
        prediction_hash = _hash_fields(
            (
                self.case_id,
                self.observation_hash,
                self.prompt_hash,
                raw_hash,
                label.value if label is not None else "",
            )
        )
        if self.raw_output_hash != raw_hash:
            fail_validation("model_raw_output_hash", "raw model output hash mismatch")
        if self.label is not label:
            fail_validation("model_output_label", "model label does not match raw output")
        if self.prediction_hash != prediction_hash:
            fail_validation("model_prediction_hash", "model prediction hash mismatch")
        return self


class RecordedModelGeneration(StrictContract):
    """Ordered hash-chain receipt for one exact model/input generation."""

    model_manifest_hash: Sha256Hex
    model_snapshot_hash: Sha256Hex
    input_set_hash: Sha256Hex
    prediction_hashes: Annotated[tuple[Sha256Hex, ...], Field(min_length=36, max_length=36)]
    generation_hash: Sha256Hex

    @model_validator(mode="after")
    def generation_is_bound(self) -> Self:
        """Reject repeated predictions or a receipt hash not bound to all outputs."""
        if len(set(self.prediction_hashes)) != len(self.prediction_hashes):
            fail_validation("model_prediction_duplicate", "model prediction hashes repeat")
        expected = _hash_fields(
            (
                self.model_manifest_hash,
                self.model_snapshot_hash,
                self.input_set_hash,
                *self.prediction_hashes,
            )
        )
        if self.generation_hash != expected:
            fail_validation("model_generation_hash", "model generation hash mismatch")
        return self


def build_model_context(
    model_manifest_hash: Sha256Hex,
    cases: tuple[ModelCaseBinding, ...],
) -> ModelEvidenceContext:
    """Build the expected ordered held-out input receipt."""
    return ModelEvidenceContext(
        model_manifest_hash=model_manifest_hash,
        input_set_hash=_hash_fields(tuple(_case_hash(case) for case in cases)),
        cases=cases,
    )


def build_model_prediction(
    case: ModelCaseBinding,
    raw_output: str,
) -> RecordedModelPrediction:
    """Retain and content-bind one raw output to its exact input case."""
    raw_hash = hashlib.sha256(raw_output.encode()).hexdigest()
    label = _parsed_label(raw_output)
    return RecordedModelPrediction(
        case_id=case.case_id,
        label=label,
        observation_hash=case.observation_hash,
        prompt_hash=case.prompt_hash,
        raw_output=raw_output,
        raw_output_hash=raw_hash,
        prediction_hash=_hash_fields(
            (
                case.case_id,
                case.observation_hash,
                case.prompt_hash,
                raw_hash,
                label.value if label is not None else "",
            )
        ),
    )


def build_model_generation(
    context: ModelEvidenceContext,
    predictions: tuple[RecordedModelPrediction, ...],
    model_snapshot_hash: Sha256Hex,
) -> RecordedModelGeneration:
    """Build the complete manifest/input/prediction hash-chain receipt."""
    prediction_hashes = tuple(prediction.prediction_hash for prediction in predictions)
    return RecordedModelGeneration(
        model_manifest_hash=context.model_manifest_hash,
        model_snapshot_hash=model_snapshot_hash,
        input_set_hash=context.input_set_hash,
        prediction_hashes=prediction_hashes,
        generation_hash=_hash_fields(
            (
                context.model_manifest_hash,
                model_snapshot_hash,
                context.input_set_hash,
                *prediction_hashes,
            )
        ),
    )
