#!/usr/bin/env -S uv run --project backend python
# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["pydantic==2.13.4"]
# ///
# pyright: reportPrivateUsage=false, reportUnusedCallResult=false

# ─── How to run ───
# Imported by visual_qa_manifest.py; run the wrapper instead.
# ────────────────

"""Filesystem and diagnostic assertions for visual-QA captures."""

from __future__ import annotations

import hashlib
import struct
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError
from telco_twin.domain.build_info import UiBuildInfo

from scripts import visual_qa_types as types
from scripts.visual_qa_types import Manifest, VisualQaError, _read_json, _scan_untrusted


def _safe_capture_path(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if (
        candidate.is_absolute()
        or "\x00" in relative
        or any(part == ".." for part in candidate.parts)
    ):
        raise VisualQaError("path-traversal", relative)
    if candidate.suffix.lower() != ".png":
        raise VisualQaError("invalid-capture-path", relative)
    resolved = (root / candidate).resolve(strict=False)
    try:
        resolved.relative_to(root.resolve())
    except ValueError as error:
        raise VisualQaError("path-traversal", relative) from error
    if not resolved.is_file() or resolved.is_symlink():
        raise VisualQaError("capture-missing", relative)
    return resolved


def _png_dimensions(path: Path) -> tuple[int, int]:
    try:
        data = path.read_bytes()
    except OSError as error:
        raise VisualQaError("capture-missing", path.as_posix()) from error
    if len(data) < 29 or data[:8] != types.PNG_SIGNATURE or data[12:16] != b"IHDR":
        raise VisualQaError("invalid-png", path.as_posix())
    length = struct.unpack(">I", data[8:12])[0]
    if length < 13 or len(data) < 16 + length:
        raise VisualQaError("invalid-png", path.as_posix())
    width, height = struct.unpack(">II", data[16:24])
    if width < 1 or height < 1:
        raise VisualQaError("invalid-dimensions", path.as_posix())
    return width, height


def _fresh(
    path: Path, captured_at: datetime, now: datetime, max_age: timedelta
) -> None:
    try:
        modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
    except OSError as error:
        raise VisualQaError("capture-missing", path.as_posix()) from error
    if (
        now - captured_at > max_age
        or now - modified > max_age
        or captured_at - now > timedelta(minutes=1)
        or modified - now > timedelta(minutes=1)
    ):
        raise VisualQaError("stale-capture", path.as_posix())


def assert_manifest(
    manifest: Manifest,
    build_info_path: Path,
    root: Path,
    *,
    now: datetime,
    max_age: timedelta,
) -> None:
    """Verify identity, exact coverage, fresh PNGs, and zero blocking diagnostics."""
    build_value = _read_json(build_info_path)
    _scan_untrusted(build_value)
    if not isinstance(build_value, dict) or "image_digest" in build_value:
        raise VisualQaError("build-info-mismatch", "UI build-info required")
    try:
        build = UiBuildInfo.model_validate(build_value)
    except ValidationError as error:
        raise VisualQaError(
            "build-info-mismatch", str(error).splitlines()[0]
        ) from error
    try:
        actual_build_hash = hashlib.sha256(build_info_path.read_bytes()).hexdigest()
    except OSError as error:
        raise VisualQaError("build-info-missing", build_info_path.as_posix()) from error
    if (
        actual_build_hash != manifest.build_info_sha
        or build.runtime_source_commit_sha != manifest.source_sha
        or build.release_commit_sha != manifest.release_sha
    ):
        raise VisualQaError("build-info-mismatch", "source-release-build")
    if (
        len(manifest.reviewers) != 2
        or len({reviewer.reviewer_id for reviewer in manifest.reviewers}) != 2
    ):
        raise VisualQaError("reviewer-count", str(len(manifest.reviewers)))
    for reviewer in manifest.reviewers:
        if not reviewer.approved or (
            reviewer.source_sha,
            reviewer.release_sha,
            reviewer.build_info_sha,
        ) != (manifest.source_sha, manifest.release_sha, manifest.build_info_sha):
            raise VisualQaError("reviewer-mismatch", reviewer.reviewer_id)
    expected = {
        (route, state, viewport)
        for route in types.ROUTES
        for state in types.STATES
        for viewport in types.VIEWPORTS
    }
    actual = {
        (capture.route, capture.state, capture.viewport)
        for capture in manifest.captures
    }
    capture_paths = tuple(capture.path for capture in manifest.captures)
    if (
        actual != expected
        or len(actual) != len(manifest.captures)
        or len(set(capture_paths)) != len(capture_paths)
    ):
        raise VisualQaError(
            "coverage-mismatch", f"expected={len(expected)} actual={len(actual)}"
        )
    for capture in manifest.captures:
        if (capture.source_sha, capture.release_sha, capture.build_info_sha) != (
            manifest.source_sha,
            manifest.release_sha,
            manifest.build_info_sha,
        ):
            raise VisualQaError("capture-identity-mismatch", capture.path)
        if capture.axe_serious != 0 or capture.axe_critical != 0:
            raise VisualQaError("axe-violations", capture.path)
        if capture.console_errors != 0:
            raise VisualQaError("console-errors", capture.path)
        if capture.network_unexpected != 0:
            raise VisualQaError("network-errors", capture.path)
        path = _safe_capture_path(root, capture.path)
        if _png_dimensions(path) != (capture.width, capture.height):
            raise VisualQaError("dimensions-mismatch", capture.path)
        _fresh(path, capture.captured_at, now, max_age)
