#!/usr/bin/env -S uv run --project backend python
# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["pydantic==2.13.4", "rfc8785>=0.1.4,<0.2"]
# ///
# pyright: reportPrivateUsage=false, reportUnusedCallResult=false, reportUnusedFunction=false

# ─── How to run ───
# Imported by visual_qa_checks.py; run the wrapper instead.
# ────────────────

"""External reviewer-receipt attribution and subject binding."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

import rfc8785

if TYPE_CHECKING:
    from pydantic import JsonValue

from scripts import visual_qa_types as types
from scripts.visual_qa_types import (
    Manifest,
    Reviewer,
    VisualQaError,
    _read_json,
    _required,
    _scan_untrusted,
    _sha,
    _sha256,
    _string,
)


def _capture_value(capture: types.Capture) -> dict[str, JsonValue]:
    axe: dict[str, JsonValue] = {
        "serious": capture.axe_serious,
        "critical": capture.axe_critical,
    }
    console: dict[str, JsonValue] = {"errors": capture.console_errors}
    network: dict[str, JsonValue] = {"unexpected": capture.network_unexpected}
    return {
        "route": capture.route,
        "state": capture.state,
        "viewport": capture.viewport,
        "path": capture.path,
        "width": capture.width,
        "height": capture.height,
        "sha256": capture.sha256,
        "captured_at": capture.captured_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_commit_sha": capture.source_sha,
        "release_commit_sha": capture.release_sha,
        "build_info_sha256": capture.build_info_sha,
        "axe": axe,
        "console": console,
        "network": network,
    }


def subject_hash(manifest: Manifest) -> str:
    """Hash all capture metadata and byte hashes without reviewer circularity."""
    subject: dict[str, JsonValue] = {
        "schema_version": types.SCHEMA_VERSION,
        "source_commit_sha": manifest.source_sha,
        "release_commit_sha": manifest.release_sha,
        "build_info_sha256": manifest.build_info_sha,
        "captures": [_capture_value(capture) for capture in manifest.captures],
    }
    return hashlib.sha256(rfc8785.dumps(subject) + b"\n").hexdigest()


def _receipt_path(root: Path, reviewer: Reviewer) -> Path:
    relative = Path(reviewer.receipt_path)
    if (
        relative.is_absolute()
        or "\x00" in reviewer.receipt_path
        or ".." in relative.parts
        or relative.suffix != ".json"
    ):
        raise VisualQaError("path-traversal", reviewer.receipt_path)
    candidate = root / relative
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise VisualQaError("path-traversal", reviewer.receipt_path)
    try:
        _ = candidate.resolve(strict=False).relative_to(root.resolve())
    except ValueError as error:
        raise VisualQaError("path-traversal", reviewer.receipt_path) from error
    if not candidate.is_file():
        raise VisualQaError("reviewer-receipt-missing", reviewer.receipt_path)
    return candidate


def _assert_receipt(manifest: Manifest, reviewer: Reviewer, root: Path) -> None:
    path = _receipt_path(root, reviewer)
    try:
        encoded = path.read_bytes()
    except OSError as error:
        raise VisualQaError(
            "reviewer-receipt-missing", reviewer.receipt_path
        ) from error
    if hashlib.sha256(encoded).hexdigest() != reviewer.receipt_sha:
        raise VisualQaError("reviewer-receipt-hash", reviewer.role)
    value = _read_json(path)
    _scan_untrusted(value, "reviewer-receipt")
    if not isinstance(value, dict):
        raise VisualQaError("reviewer-attribution", reviewer.role)
    required = (
        "schema_version",
        "reviewer_role",
        "reviewer_run_id",
        "verdict",
        "source_commit_sha",
        "release_commit_sha",
        "build_info_sha256",
        "subject_sha256",
    )
    _required(value, required, required, "reviewer-receipt")
    expected = (
        types.SCHEMA_VERSION,
        reviewer.role,
        reviewer.run_id,
        "approved",
        manifest.source_sha,
        manifest.release_sha,
        manifest.build_info_sha,
        manifest.subject_sha,
    )
    actual = (
        _string(value, "schema_version", "reviewer-receipt"),
        _string(value, "reviewer_role", "reviewer-receipt"),
        _string(value, "reviewer_run_id", "reviewer-receipt"),
        _string(value, "verdict", "reviewer-receipt"),
        _sha(_string(value, "source_commit_sha", "reviewer-receipt"), "source"),
        _sha(_string(value, "release_commit_sha", "reviewer-receipt"), "release"),
        _sha256(_string(value, "build_info_sha256", "reviewer-receipt"), "build-info"),
        _sha256(_string(value, "subject_sha256", "reviewer-receipt"), "subject"),
    )
    if actual != expected or encoded != rfc8785.dumps(value) + b"\n":
        raise VisualQaError("reviewer-mismatch", reviewer.role)


def assert_reviewers(manifest: Manifest, root: Path, reviewer_count: int) -> None:
    """Require fixed roles, distinct runs, exact receipts, and subject binding."""
    if len(manifest.reviewers) != reviewer_count:
        raise VisualQaError("reviewer-count", str(len(manifest.reviewers)))
    roles = tuple(reviewer.role for reviewer in manifest.reviewers)
    runs = tuple(reviewer.run_id for reviewer in manifest.reviewers)
    if len(set(roles)) != len(roles) or any(
        role not in types.REVIEWER_ROLES for role in roles
    ):
        raise VisualQaError("reviewer-attribution", ",".join(roles))
    if reviewer_count == len(types.REVIEWER_ROLES) and set(roles) != set(
        types.REVIEWER_ROLES
    ):
        raise VisualQaError("reviewer-attribution", ",".join(roles))
    if len(set(runs)) != len(runs):
        raise VisualQaError("reviewer-independence", ",".join(runs))
    if subject_hash(manifest) != manifest.subject_sha:
        raise VisualQaError("subject-mismatch", manifest.subject_sha)
    for reviewer in manifest.reviewers:
        _assert_receipt(manifest, reviewer, root)
