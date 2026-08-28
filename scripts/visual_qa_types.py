#!/usr/bin/env -S uv run --project backend python
# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["pydantic==2.13.4"]
# ///
# pyright: reportUnusedFunction=false, reportImplicitOverride=false

# ─── How to run ───
# Imported by visual_qa_manifest.py; run the wrapper instead.
# ────────────────

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from pydantic import JsonValue, TypeAdapter, ValidationError

SCHEMA_VERSION: Final = "1.0"
ROUTES: Final = (
    "ScenarioWorkbench",
    "RunDetail",
    "EvidenceBoard",
    "BenchmarkLab",
    "About",
)
STATES: Final = ("loading", "empty", "error", "stale", "rejected", "approved", "demo")
VIEWPORTS: Final = ("desktop", "mobile")
REVIEWER_ROLES: Final = ("visual-fidelity", "accessibility")
PNG_SIGNATURE: Final = b"\x89PNG\r\n\x1a\n"
SHA1_PATTERN: Final = re.compile(r"[0-9a-f]{40}\Z")
SHA256_PATTERN: Final = re.compile(r"[0-9a-f]{64}\Z")
TIMESTAMP_PATTERN: Final = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
SECRET_PATTERN: Final = re.compile(
    r"(?i)(?:bearer\s+|private[ _-]?key|api[ _-]?key|password|secret|credential|authorization|token)"
)
FORBIDDEN_FIXTURE_PATTERN: Final = re.compile(
    r"(?i)(?:mock|fake|production|fixture\s+route)"
)
JSON_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


def _reject_duplicate_keys(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    keys = tuple(key for key, _ in pairs)
    if len(keys) != len(set(keys)):
        raise VisualQaError("invalid-json", "duplicate JSON key")
    return dict(pairs)


@dataclass(frozen=True, slots=True)
class Capture:
    """One immutable browser screenshot and its machine checks."""

    route: str
    state: str
    viewport: str
    path: str
    width: int
    height: int
    sha256: str
    captured_at: datetime
    source_sha: str
    release_sha: str
    build_info_sha: str
    axe_serious: int
    axe_critical: int
    console_errors: int
    network_unexpected: int


@dataclass(frozen=True, slots=True)
class Reviewer:
    """One external approval receipt reference."""

    role: str
    run_id: str
    receipt_path: str
    receipt_sha: str


@dataclass(frozen=True, slots=True)
class Manifest:
    """Parsed strict visual-QA manifest."""

    source_sha: str
    release_sha: str
    build_info_sha: str
    subject_sha: str
    captures: tuple[Capture, ...]
    reviewers: tuple[Reviewer, ...]


@dataclass(frozen=True, slots=True)
class VisualRequirements:
    """Requested evidence matrix and independent review count."""

    routes: tuple[str, ...]
    states: tuple[str, ...]
    viewports: tuple[str, ...]
    reviewer_count: int


@dataclass(frozen=True, slots=True)
class VisualQaError(Exception):
    """Stable fail-closed visual evidence error."""

    code: str
    detail: str

    def __str__(self) -> str:
        return f"visual-qa-error:{self.code}:{self.detail}"


def _required(
    mapping: Mapping[str, JsonValue],
    required: tuple[str, ...],
    allowed: tuple[str, ...],
    context: str,
) -> None:
    missing = tuple(key for key in required if key not in mapping)
    extra = tuple(key for key in mapping if key not in allowed)
    if missing:
        raise VisualQaError("schema-mismatch", f"{context}:missing:{','.join(missing)}")
    if extra:
        raise VisualQaError("schema-mismatch", f"{context}:extra:{','.join(extra)}")


def _string(mapping: Mapping[str, JsonValue], key: str, context: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise VisualQaError("schema-mismatch", f"{context}:{key}")
    return value


def _integer(mapping: Mapping[str, JsonValue], key: str, context: str) -> int:
    value = mapping.get(key)
    if type(value) is not int:
        raise VisualQaError("schema-mismatch", f"{context}:{key}")
    return value


def _boolean(mapping: Mapping[str, JsonValue], key: str, context: str) -> bool:
    value = mapping.get(key)
    if type(value) is not bool:
        raise VisualQaError("schema-mismatch", f"{context}:{key}")
    return value


def _mapping(
    mapping: Mapping[str, JsonValue], key: str, context: str
) -> Mapping[str, JsonValue]:
    value = mapping.get(key)
    if not isinstance(value, dict):
        raise VisualQaError("schema-mismatch", f"{context}:{key}")
    return value


def _sha(value: str, field: str) -> str:
    if not SHA1_PATTERN.fullmatch(value):
        raise VisualQaError("schema-mismatch", field)
    return value


def _sha256(value: str, field: str) -> str:
    if not SHA256_PATTERN.fullmatch(value):
        raise VisualQaError("schema-mismatch", field)
    return value


def _timestamp(value: str, field: str) -> datetime:
    if not TIMESTAMP_PATTERN.fullmatch(value):
        raise VisualQaError("schema-mismatch", field)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise VisualQaError("schema-mismatch", field) from error
    return parsed.astimezone(UTC)


def _scan_untrusted(value: JsonValue, path: str = "manifest") -> None:
    if isinstance(value, str):
        if SECRET_PATTERN.search(value):
            raise VisualQaError("secret-data", path)
        if FORBIDDEN_FIXTURE_PATTERN.search(value):
            raise VisualQaError("fixture-route", path)
        return
    if isinstance(value, dict):
        for key, nested in value.items():
            if SECRET_PATTERN.search(key):
                raise VisualQaError("secret-data", f"{path}.{key}")
            if FORBIDDEN_FIXTURE_PATTERN.search(key):
                raise VisualQaError("fixture-route", f"{path}.{key}")
            _scan_untrusted(nested, f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, nested in enumerate(value):
            _scan_untrusted(nested, f"{path}[{index}]")


def _read_json(path: Path) -> JsonValue:
    try:
        return JSON_ADAPTER.validate_python(
            json.loads(path.read_bytes(), object_pairs_hook=_reject_duplicate_keys)
        )
    except (OSError, ValueError, ValidationError) as error:
        raise VisualQaError("invalid-json", path.as_posix()) from error
