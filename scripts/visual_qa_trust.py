#!/usr/bin/env -S uv run --project backend python
# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["pydantic==2.13.4", "pynacl>=1.6.2,<2", "rfc8785>=0.1.4,<0.2"]
# ///
# pyright: reportPrivateUsage=false, reportUnusedFunction=false

# ─── How to run ───
# Imported by visual_qa_reviewers.py; run the wrapper instead.
# ────────────────

"""Pre-bound Ed25519 reviewer trust descriptor parsing."""

from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

import rfc8785
from nacl.signing import VerifyKey

if TYPE_CHECKING:
    from pydantic import JsonValue

from scripts import visual_qa_types as types
from scripts.visual_qa_types import (
    VisualQaError,
    _read_json_bytes,
    _required,
    _string,
)

REVIEW_DOMAIN: Final = b"telco-twin-visual-review:v1\0"


@dataclass(frozen=True, slots=True)
class ReviewerRoot:
    """One source-bound reviewer role and Ed25519 verification key."""

    role: str
    key_id: str
    verify_key: VerifyKey


@dataclass(frozen=True, slots=True)
class ReviewerTrust:
    """The complete immutable two-reviewer trust set."""

    roots: tuple[ReviewerRoot, ...]

    def for_role(self, role: str) -> ReviewerRoot:
        for root in self.roots:
            if root.role == role:
                return root
        raise VisualQaError("reviewer-attribution", role)


def _base64url(value: str, field: str) -> bytes:
    try:
        decoded = base64.b64decode(
            value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
        )
    except (ValueError, TypeError) as error:
        raise VisualQaError("reviewer-trust-schema", field) from error
    canonical = base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii")
    if canonical != value:
        raise VisualQaError("reviewer-trust-schema", field)
    return decoded


def _root(value: JsonValue, index: int) -> ReviewerRoot:
    if not isinstance(value, dict):
        raise VisualQaError("reviewer-trust-schema", f"reviewers[{index}]")
    required = ("role", "key_id", "public_key")
    _required(value, required, required, f"reviewers[{index}]")
    role = _string(value, "role", f"reviewers[{index}]")
    key_id = _string(value, "key_id", f"reviewers[{index}]")
    if role not in types.REVIEWER_ROLES or not re.fullmatch(
        r"[a-z][a-z0-9-]{7,95}", key_id
    ):
        raise VisualQaError("reviewer-trust-schema", role)
    public_key = _base64url(
        _string(value, "public_key", f"reviewers[{index}]"), "public_key"
    )
    if len(public_key) != 32:
        raise VisualQaError("reviewer-trust-schema", "public_key")
    return ReviewerRoot(role=role, key_id=key_id, verify_key=VerifyKey(public_key))


def load_reviewer_trust(path: Path, expected_hash: str) -> ReviewerTrust:
    """Load canonical roots whose exact bytes are bound into UI build-info."""
    try:
        encoded = path.read_bytes()
    except OSError as error:
        raise VisualQaError("reviewer-trust-missing", path.as_posix()) from error
    if hashlib.sha256(encoded).hexdigest() != expected_hash:
        raise VisualQaError("reviewer-trust-hash", path.as_posix())
    value = _read_json_bytes(encoded, path.as_posix())
    if not isinstance(value, dict):
        raise VisualQaError("reviewer-trust-schema", "descriptor")
    required = ("schema_version", "reviewers")
    _required(value, required, required, "reviewer-trust")
    if _string(value, "schema_version", "reviewer-trust") != types.SCHEMA_VERSION:
        raise VisualQaError("reviewer-trust-schema", "schema_version")
    reviewers = value.get("reviewers")
    if not isinstance(reviewers, list):
        raise VisualQaError("reviewer-trust-schema", "reviewers")
    roots = tuple(_root(item, index) for index, item in enumerate(reviewers))
    roles = tuple(root.role for root in roots)
    keys = tuple(bytes(root.verify_key) for root in roots)
    if set(roles) != set(types.REVIEWER_ROLES) or len(roots) != len(
        types.REVIEWER_ROLES
    ):
        raise VisualQaError("reviewer-attribution", ",".join(roles))
    if len(set(keys)) != len(keys):
        raise VisualQaError("reviewer-root-independence", "duplicate public key")
    if encoded != rfc8785.dumps(value) + b"\n":
        raise VisualQaError("reviewer-trust-schema", "canonical JSON")
    return ReviewerTrust(roots=roots)
