#!/usr/bin/env -S uv run --project backend python
# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["pydantic==2.13.4"]
# ///
# pyright: reportPrivateUsage=false, reportUnusedFunction=false

# ─── How to run ───
# Imported by visual_qa_manifest.py; run the wrapper instead.
# ────────────────

"""CLI-only time, requirement, and repository path parsing."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from scripts.visual_qa_types import VisualQaError, _timestamp


def parse_now(value: str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    return _timestamp(value, "now")


def csv_requirement(
    value: str | None, allowed: tuple[str, ...], field: str
) -> tuple[str, ...]:
    if value is None:
        return allowed
    parts = tuple(part.strip() for part in value.split(",") if part.strip())
    if (
        not parts
        or len(parts) != len(set(parts))
        or any(part not in allowed for part in parts)
    ):
        raise VisualQaError("requirement-invalid", field)
    return parts


def repo_path(root: Path, value: Path, field: str) -> Path:
    if value.is_absolute() or "\x00" in value.as_posix() or ".." in value.parts:
        raise VisualQaError("path-traversal", field)
    candidate = root / value
    current = root
    for part in value.parts:
        current /= part
        if current.is_symlink():
            raise VisualQaError("path-traversal", field)
    try:
        _ = candidate.resolve(strict=False).relative_to(root.resolve())
    except ValueError as error:
        raise VisualQaError("path-traversal", field) from error
    return candidate
