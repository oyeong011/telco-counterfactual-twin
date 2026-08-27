"""Normative project validation for generated schema annotations and Pydantic rules."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, ClassVar, Final, Never

import typer
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from telco_twin.schema_export import (
    CERTIFICATE_WINDOW_INVARIANTS,
    CONTRACT_INVARIANTS,
    CONTRACT_MODELS,
    KEY_POLICY_ANNOTATION,
    CertificateWindowInvariant,
    DurationInvariant,
    KeyPolicyAnnotation,
)

DEFAULT_SCHEMA_DIR: Final = Path("specs/schemas")


class ContractSchemaMetadata(BaseModel):
    """Machine-consumed annotations attached to one generated JSON Schema."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    invariants: tuple[DurationInvariant, ...] = Field(alias="x-telco-twin-invariants")
    key_policy: KeyPolicyAnnotation = Field(alias="x-telco-twin-key-policy")
    certificate_window: CertificateWindowInvariant | None = Field(
        alias="x-telco-twin-certificate-window",
        default=None,
    )


def _fail(code: str) -> Never:
    typer.echo(code, err=True)
    raise typer.Exit(code=3)


def _first_error_code(error: ValidationError) -> str:
    errors = error.errors()
    return errors[0]["type"] if errors else "validation-error"


def validate_contract(schema_name: str, input_path: Path, schema_dir: Path) -> None:
    """Validate annotations and then apply the normative Pydantic boundary."""
    model = CONTRACT_MODELS.get(schema_name)
    if model is None:
        _fail(f"contract-schema-unknown:{schema_name}")
    schema_path = schema_dir / f"{schema_name}.schema.json"
    try:
        metadata = ContractSchemaMetadata.model_validate_json(schema_path.read_bytes())
    except OSError:
        _fail(f"contract-schema-unreadable:{schema_name}")
    except ValidationError:
        _fail(f"contract-schema-annotations-invalid:{schema_name}")
    expected = CONTRACT_INVARIANTS.get(schema_name, ())
    expected_window = CERTIFICATE_WINDOW_INVARIANTS.get(schema_name)
    if (
        metadata.invariants != expected
        or metadata.key_policy != KEY_POLICY_ANNOTATION
        or metadata.certificate_window != expected_window
    ):
        _fail(f"contract-schema-annotations-stale:{schema_name}")
    try:
        _ = model.model_validate_json(input_path.read_bytes())
    except OSError:
        _fail(f"contract-input-unreadable:{schema_name}")
    except ValidationError as error:
        _fail(f"contract-invalid:{schema_name}:{_first_error_code(error)}")
    typer.echo(f"contract-valid:{schema_name}")


def main(
    schema_name: Annotated[str, typer.Option("--schema")],
    input_path: Annotated[Path, typer.Option("--input")],
    schema_dir: Annotated[Path, typer.Option("--schema-dir")] = DEFAULT_SCHEMA_DIR,
) -> None:
    """Validate one contract with generated metadata plus cross-field rules."""
    validate_contract(schema_name, input_path, schema_dir)
