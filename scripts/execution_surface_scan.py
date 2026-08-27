"""Explicit-root discovery and JSON-schema execution-surface scanning."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import ClassVar, Final, assert_never

from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter, ValidationError

from scripts.execution_surface_policy import is_mutation_name
from scripts.execution_surface_python import python_findings
from scripts.execution_surface_types import MutationSurface

JSON_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)
EXCLUDED_DIRECTORY_NAMES: Final = frozenset({".venv", "__pycache__"})
REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[1]
REVIEWED_ADAPTER_ROOTS: Final = (
    (REPOSITORY_ROOT / "backend/src/telco_twin/bootstrap").resolve(),
    (REPOSITORY_ROOT / "backend/src/telco_twin/deploy").resolve(),
)


class _JsonEnvelope(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    value: JsonValue


def _excluded(path: Path) -> bool:
    resolved = path.resolve()
    return bool(set(path.parts) & EXCLUDED_DIRECTORY_NAMES) or any(
        resolved.is_relative_to(root) for root in REVIEWED_ADAPTER_ROOTS
    )


def _schema_fields(value: JsonValue) -> Iterable[str]:
    envelope = _JsonEnvelope(value=value)
    match envelope.value:
        case dict() as mapping:
            properties = mapping.get("properties")
            if isinstance(properties, dict):
                yield from properties
            for nested in mapping.values():
                yield from _schema_fields(nested)
        case list() as items:
            for item in items:
                yield from _schema_fields(item)
        case None:
            return
        case str() | bool() | int() | float():
            return
        case _:
            assert_never(envelope.value)


def _schema_findings(path: Path) -> tuple[MutationSurface, ...]:
    try:
        value = JSON_ADAPTER.validate_json(path.read_bytes())
    except (OSError, ValidationError) as error:
        return (
            MutationSurface(str(path), 0, "schema-parse-error", type(error).__name__),
        )
    return tuple(
        MutationSurface(str(path), 0, "schema-field", name)
        for name in _schema_fields(value)
        if is_mutation_name(name)
    )


def _discovered_files(path: Path) -> tuple[Path, ...]:
    if path.is_file():
        return (
            (path,) if path.suffix in {".py", ".json"} and not _excluded(path) else ()
        )
    candidates = (
        *path.rglob("*.py"),
        *path.rglob("*.json"),
    )
    return tuple(
        sorted(candidate for candidate in candidates if not _excluded(candidate))
    )


def scan_paths(paths: Sequence[Path]) -> tuple[MutationSurface, ...]:
    """Return sorted findings and fail closed for every absent explicit root."""
    findings: set[MutationSurface] = set()
    files: set[Path] = set()
    for path in paths:
        if not path.exists():
            findings.add(
                MutationSurface(str(path), 0, "scan-root-error", "missing-root")
            )
            continue
        files.update(_discovered_files(path))
    for path in sorted(files):
        if path.suffix == ".py":
            findings.update(python_findings(path))
        else:
            findings.update(_schema_findings(path))
    return tuple(sorted(findings))
