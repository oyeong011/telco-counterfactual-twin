"""Typed process helpers for independent external-schema tests."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter

from .contract_cases import REPO_ROOT
from .contract_payloads import JsonObject

if TYPE_CHECKING:
    from pathlib import Path

JSON_OBJECT_ADAPTER: Final[TypeAdapter[JsonObject]] = TypeAdapter(JsonObject)
CHECK_JSONSCHEMA: Final = "check-jsonschema"


def read_json(path: Path) -> JsonObject:
    """Parse one fixture or generated schema as a typed JSON object."""
    return JSON_OBJECT_ADAPTER.validate_json(path.read_bytes())


def write_json(path: Path, value: JsonObject) -> None:
    """Write one test-only JSON payload."""
    _ = path.write_text(json.dumps(value), encoding="utf-8")


def check_schema(schema_name: str, input_path: Path) -> subprocess.CompletedProcess[str]:
    """Run the independent JSON Schema validator."""
    return subprocess.run(
        (
            CHECK_JSONSCHEMA,
            "--schemafile",
            str(REPO_ROOT / f"specs/schemas/{schema_name}.schema.json"),
            str(input_path),
        ),
        check=False,
        capture_output=True,
        text=True,
    )


def run_project_validator(
    schema_name: str,
    input_path: Path,
) -> subprocess.CompletedProcess[str]:
    """Run the normative project validator in a fresh process."""
    return subprocess.run(
        (
            sys.executable,
            str(REPO_ROOT / "scripts/validate_contract.py"),
            "--schema",
            schema_name,
            "--input",
            str(input_path),
        ),
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
