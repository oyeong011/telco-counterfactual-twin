"""Deterministic JSON Schema export and fixture-validation behavior."""

from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Annotated, ClassVar, Final, Literal, Never

import typer
from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter, ValidationError

from telco_twin.domain._key_policy import (
    AUTHORITY_KEY_TOKENS,
    COLLAPSED_ACTION_PREFIXES,
    COLLAPSED_ACTION_TARGETS,
    COLLAPSED_ARBITRARY_URL_STEMS,
    COLLAPSED_AUTHORITY_STEMS,
    COLLAPSED_DIRECT_PII_STEMS,
    COLLAPSED_IDENTIFIER_STEMS,
    COLLAPSED_IDENTITY_SUBJECTS,
    COLLAPSED_SECRET_STEMS,
    FORBIDDEN_KEY_COMBINATIONS,
    IDENTIFIER_TOKENS,
    IDENTITY_SUBJECT_TOKENS,
    KEY_POLICY_ALLOW_EXAMPLES,
    KEY_POLICY_VERSION,
    PII_KEY_TOKENS,
    SECRET_KEY_TOKENS,
)
from telco_twin.domain.approval import ApprovalProof, ApprovalRequest, SessionKeyCertificate
from telco_twin.domain.build_info import ServiceBuildInfo, UiBuildInfo
from telco_twin.domain.event import Event
from telco_twin.domain.evidence import EvidenceCard
from telco_twin.domain.intervention import TypedPatch
from telco_twin.domain.scenario import Scenario
from telco_twin.domain.simulation_result import SimulationResult
from telco_twin.domain.telemetry import Telemetry
from telco_twin.domain.topology import Topology

if TYPE_CHECKING:
    from collections.abc import Mapping

EXPECTED_SCHEMA_NAMES: Final = (
    "topology",
    "telemetry",
    "scenario",
    "event",
    "typed-patch",
    "simulation-result",
    "approval-request",
    "session-key-certificate",
    "approval-proof",
    "evidence-card",
    "service-build-info",
    "ui-build-info",
)
CONTRACT_MODELS: Final[Mapping[str, type[BaseModel]]] = MappingProxyType(
    {
        "topology": Topology,
        "telemetry": Telemetry,
        "scenario": Scenario,
        "event": Event,
        "typed-patch": TypedPatch,
        "simulation-result": SimulationResult,
        "approval-request": ApprovalRequest,
        "session-key-certificate": SessionKeyCertificate,
        "approval-proof": ApprovalProof,
        "evidence-card": EvidenceCard,
        "service-build-info": ServiceBuildInfo,
        "ui-build-info": UiBuildInfo,
    }
)
JSON_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)
JSON_OBJECT_ADAPTER: Final[TypeAdapter[dict[str, JsonValue]]] = TypeAdapter(dict[str, JsonValue])
DEFAULT_OUT_DIR: Final = Path("specs/schemas")


class DurationInvariant(BaseModel):
    """Machine-readable cross-field duration rule beyond plain JSON Schema."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    code: Literal["ttl_60_seconds"]
    kind: Literal["duration_seconds"]
    start_field: str
    end_field: str
    seconds: Literal[60]
    json_schema_support: Literal["annotation_only"]
    enforced_by: Literal["scripts/validate_contract.py"]

    def as_json(self) -> JsonValue:
        """Return a typed JSON value for schema annotation."""
        return JSON_ADAPTER.validate_json(self.model_dump_json())


class KeyPolicyAnnotation(BaseModel):
    """Recursive semantic-key policy enforced by the project validator."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    version: str
    recursive: Literal[True]
    pii_tokens: tuple[str, ...]
    identity_subject_tokens: tuple[str, ...]
    identifier_tokens: tuple[str, ...]
    authority_tokens: tuple[str, ...]
    secret_tokens: tuple[str, ...]
    collapsed_direct_pii_stems: tuple[str, ...]
    collapsed_identity_subjects: tuple[str, ...]
    collapsed_identifier_stems: tuple[str, ...]
    collapsed_authority_stems: tuple[str, ...]
    collapsed_action_prefixes: tuple[str, ...]
    collapsed_action_targets: tuple[str, ...]
    collapsed_arbitrary_url_stems: tuple[str, ...]
    collapsed_secret_stems: tuple[str, ...]
    forbidden_combinations: tuple[tuple[str, ...], ...]
    allow_examples: tuple[str, ...]
    json_schema_support: Literal["annotation_only"]
    enforced_by: Literal["scripts/validate_contract.py"]

    def as_json(self) -> JsonValue:
        """Return a typed JSON value for schema annotation."""
        return JSON_ADAPTER.validate_json(self.model_dump_json())


class CertificateWindowInvariant(BaseModel):
    """Proof interval containment rule beyond plain JSON Schema."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    code: Literal["proof-certificate-window"]
    kind: Literal["contained_interval"]
    proof_start_field: Literal["approved_at"]
    proof_end_field: Literal["expires_at"]
    certificate_start_field: Literal["issued_at"]
    certificate_end_field: Literal["expires_at"]
    ttl_consequence: Literal["equal_window_required_when_both_are_60_seconds"]
    json_schema_support: Literal["annotation_only"]
    enforced_by: Literal["scripts/validate_contract.py"]

    def as_json(self) -> JsonValue:
        """Return a typed JSON value for schema annotation."""
        return JSON_ADAPTER.validate_json(self.model_dump_json())


def _duration_rule(start_field: str, end_field: str) -> DurationInvariant:
    return DurationInvariant(
        code="ttl_60_seconds",
        kind="duration_seconds",
        start_field=start_field,
        end_field=end_field,
        seconds=60,
        json_schema_support="annotation_only",
        enforced_by="scripts/validate_contract.py",
    )


CONTRACT_INVARIANTS: Final[Mapping[str, tuple[DurationInvariant, ...]]] = MappingProxyType(
    {
        "approval-request": (_duration_rule("requested_at", "expires_at"),),
        "session-key-certificate": (_duration_rule("issued_at", "expires_at"),),
        "approval-proof": (_duration_rule("approved_at", "expires_at"),),
    }
)
KEY_POLICY_ANNOTATION: Final = KeyPolicyAnnotation(
    version=KEY_POLICY_VERSION,
    recursive=True,
    pii_tokens=PII_KEY_TOKENS,
    identity_subject_tokens=IDENTITY_SUBJECT_TOKENS,
    identifier_tokens=IDENTIFIER_TOKENS,
    authority_tokens=AUTHORITY_KEY_TOKENS,
    secret_tokens=SECRET_KEY_TOKENS,
    collapsed_direct_pii_stems=COLLAPSED_DIRECT_PII_STEMS,
    collapsed_identity_subjects=COLLAPSED_IDENTITY_SUBJECTS,
    collapsed_identifier_stems=COLLAPSED_IDENTIFIER_STEMS,
    collapsed_authority_stems=COLLAPSED_AUTHORITY_STEMS,
    collapsed_action_prefixes=COLLAPSED_ACTION_PREFIXES,
    collapsed_action_targets=COLLAPSED_ACTION_TARGETS,
    collapsed_arbitrary_url_stems=COLLAPSED_ARBITRARY_URL_STEMS,
    collapsed_secret_stems=COLLAPSED_SECRET_STEMS,
    forbidden_combinations=FORBIDDEN_KEY_COMBINATIONS,
    allow_examples=KEY_POLICY_ALLOW_EXAMPLES,
    json_schema_support="annotation_only",
    enforced_by="scripts/validate_contract.py",
)
PROOF_CERTIFICATE_WINDOW: Final = CertificateWindowInvariant(
    code="proof-certificate-window",
    kind="contained_interval",
    proof_start_field="approved_at",
    proof_end_field="expires_at",
    certificate_start_field="issued_at",
    certificate_end_field="expires_at",
    ttl_consequence="equal_window_required_when_both_are_60_seconds",
    json_schema_support="annotation_only",
    enforced_by="scripts/validate_contract.py",
)
CERTIFICATE_WINDOW_INVARIANTS: Final[Mapping[str, CertificateWindowInvariant]] = MappingProxyType(
    {"approval-proof": PROOF_CERTIFICATE_WINDOW}
)


def render_schema(name: str, model: type[BaseModel]) -> bytes:
    """Render one byte-stable JSON Schema snapshot."""
    schema = JSON_OBJECT_ADAPTER.validate_python(model.model_json_schema(mode="validation"))
    schema["x-telco-twin-invariants"] = [
        invariant.as_json() for invariant in CONTRACT_INVARIANTS.get(name, ())
    ]
    schema["x-telco-twin-key-policy"] = KEY_POLICY_ANNOTATION.as_json()
    certificate_window = CERTIFICATE_WINDOW_INVARIANTS.get(name)
    if certificate_window is not None:
        schema["x-telco-twin-certificate-window"] = certificate_window.as_json()
    rendered = json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True)
    return f"{rendered}\n".encode()


def _first_error_code(error: ValidationError) -> str:
    errors = error.errors()
    return errors[0]["type"] if errors else "validation-error"


def _fail(code: str) -> Never:
    typer.echo(code, err=True)
    raise typer.Exit(code=3)


def _validate_contract(schema_name: str, input_path: Path | None) -> None:
    model = CONTRACT_MODELS.get(schema_name)
    if model is None:
        _fail(f"contract-schema-unknown:{schema_name}")
    if input_path is None:
        _fail("contract-input-required")
    try:
        payload = input_path.read_bytes()
    except OSError:
        _fail(f"contract-input-unreadable:{schema_name}")
    try:
        _ = model.model_validate_json(payload)
    except ValidationError as error:
        _fail(f"contract-invalid:{schema_name}:{_first_error_code(error)}")
    typer.echo(f"contract-valid:{schema_name}")


def _check(out_dir: Path) -> None:
    expected_files = frozenset(f"{name}.schema.json" for name in CONTRACT_MODELS)
    actual_files = frozenset(path.name for path in out_dir.glob("*.schema.json") if path.is_file())
    extra_files = sorted(actual_files - expected_files)
    if extra_files:
        slug = extra_files[0].removesuffix(".schema.json")
        _fail(f"contract-schema-extra:{slug}")
    for name, model in CONTRACT_MODELS.items():
        path = out_dir / f"{name}.schema.json"
        if not path.is_file():
            _fail(f"contract-schema-missing:{name}")
        if path.read_bytes() != render_schema(name, model):
            _fail(f"contract-schema-stale:{name}")
    typer.echo("contract-schemas-current")


def _export(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, model in CONTRACT_MODELS.items():
        _ = (out_dir / f"{name}.schema.json").write_bytes(render_schema(name, model))
    typer.echo(f"contract-schemas-exported:{len(CONTRACT_MODELS)}")


def main(
    out_dir: Annotated[Path, typer.Option("--out-dir")] = DEFAULT_OUT_DIR,
    check: Annotated[bool, typer.Option("--check")] = False,
    validate: Annotated[str | None, typer.Option("--validate")] = None,
    input_path: Annotated[Path | None, typer.Option("--input")] = None,
) -> None:
    """Export schemas, check snapshots, or validate one JSON boundary object."""
    if tuple(CONTRACT_MODELS) != EXPECTED_SCHEMA_NAMES:
        _fail("contract-generator-incomplete")
    if validate is not None:
        if check:
            _fail("contract-mode-conflict")
        _validate_contract(validate, input_path)
        return
    if input_path is not None:
        _fail("contract-schema-required")
    if check:
        _check(out_dir)
        return
    _export(out_dir)
