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
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError
from telco_twin.domain.build_info import UiBuildInfo

from scripts.visual_qa_png import png_dimensions
from scripts.visual_qa_reviewers import ReviewerEvidenceContext, assert_reviewers
from scripts.visual_qa_trust import load_reviewer_trust
from scripts.visual_qa_types import (
    Manifest,
    VisualQaError,
    VisualRequirements,
    _read_json_bytes,
    _scan_untrusted,
)


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
    current = root
    for part in candidate.parts:
        current /= part
        if current.is_symlink():
            raise VisualQaError("path-traversal", relative)
    try:
        resolved.relative_to(root.resolve())
    except ValueError as error:
        raise VisualQaError("path-traversal", relative) from error
    if not resolved.is_file():
        raise VisualQaError("capture-missing", relative)
    return resolved


def _viewport_geometry(viewport: str, width: int, height: int, path: str) -> None:
    desktop = viewport == "desktop" and width >= 1024 and height >= 600
    mobile = viewport == "mobile" and 320 <= width <= 767 and height >= 568
    if not desktop and not mobile:
        raise VisualQaError("viewport-geometry", path)


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
    requirements: VisualRequirements,
    reviewer_trust_path: Path,
) -> None:
    """Verify identity, exact coverage, fresh PNGs, and zero blocking diagnostics."""
    try:
        build_bytes = build_info_path.read_bytes()
    except OSError as error:
        raise VisualQaError("build-info-missing", build_info_path.as_posix()) from error
    build_value = _read_json_bytes(build_bytes, build_info_path.as_posix())
    _scan_untrusted(build_value)
    if not isinstance(build_value, dict) or "image_digest" in build_value:
        raise VisualQaError("build-info-mismatch", "UI build-info required")
    try:
        build = UiBuildInfo.model_validate(build_value)
    except ValidationError as error:
        raise VisualQaError(
            "build-info-mismatch", str(error).splitlines()[0]
        ) from error
    reviewer_trust = load_reviewer_trust(reviewer_trust_path, build.trusted_root_hashes)
    actual_build_hash = hashlib.sha256(build_bytes).hexdigest()
    if (
        actual_build_hash != manifest.build_info_sha
        or build.runtime_source_commit_sha != manifest.source_sha
        or build.release_commit_sha != manifest.release_sha
    ):
        raise VisualQaError("build-info-mismatch", "source-release-build")
    expected = {
        (route, state, viewport)
        for route in requirements.routes
        for state in requirements.states
        for viewport in requirements.viewports
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
        try:
            encoded = path.read_bytes()
        except OSError as error:
            raise VisualQaError("capture-missing", capture.path) from error
        actual_hash = hashlib.sha256(encoded).hexdigest()
        if actual_hash != capture.sha256:
            raise VisualQaError("capture-hash-mismatch", capture.path)
        if png_dimensions(encoded, path) != (capture.width, capture.height):
            raise VisualQaError("dimensions-mismatch", capture.path)
        _viewport_geometry(
            capture.viewport, capture.width, capture.height, capture.path
        )
        _fresh(path, capture.captured_at, now, max_age)
    if requirements.reviewer_count != len(reviewer_trust.roots):
        raise VisualQaError("reviewer-count", str(requirements.reviewer_count))
    assert_reviewers(manifest, ReviewerEvidenceContext(root=root, trust=reviewer_trust))
