"""Signed reviewer trust and receipt fixtures for Task 9 visual tests."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Final, NotRequired, TypedDict

import rfc8785
from nacl.signing import SigningKey
from pydantic import JsonValue, TypeAdapter

JSON_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)

REVIEWER_ROLES: Final = ("visual-fidelity", "accessibility")
REVIEW_DOMAIN: Final = b"telco-twin-visual-review:v1\0"
REVIEWER_SEEDS: Final = (
    b"visual-fidelity-review-root-v1!!",
    b"accessibility-review-root-v1!!!!",
)


class CapturePayload(TypedDict):
    route: str
    state: str
    viewport: str
    path: str
    width: int
    height: int
    sha256: str
    captured_at: str
    source_commit_sha: str
    release_commit_sha: str
    build_info_sha256: str
    axe: dict[str, int]
    console: dict[str, int]
    network: dict[str, int]
    note: NotRequired[str]


class ReviewerPayload(TypedDict):
    role: str
    run_id: str
    receipt_path: str
    receipt_sha256: str


class VisualManifest(TypedDict):
    schema_version: str
    source_commit_sha: str
    release_commit_sha: str
    build_info_sha256: str
    subject_sha256: str
    captures: list[CapturePayload]
    reviewers: list[ReviewerPayload]


def canonical_bytes(value: JsonValue) -> bytes:
    """Encode one evidence object with the public RFC8785 contract."""
    return rfc8785.dumps(value) + b"\n"


def json_object(encoded: bytes) -> dict[str, JsonValue]:
    """Parse one test receipt as a typed JSON object."""
    value = JSON_ADAPTER.validate_json(encoded)
    assert isinstance(value, dict)
    return value


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def signing_keys(*, shared_key: bool = False) -> tuple[SigningKey, SigningKey]:
    """Return two deterministic test-only signing roots."""
    visual = SigningKey(REVIEWER_SEEDS[0])
    accessibility = visual if shared_key else SigningKey(REVIEWER_SEEDS[1])
    return visual, accessibility


def reviewer_trust(path: Path, *, shared_key: bool = False) -> str:
    """Write two pre-bound public reviewer roots and return canonical hash."""
    keys = signing_keys(shared_key=shared_key)
    reviewers: list[JsonValue] = [
        {
            "key_id": f"{role}-review-root-v1",
            "public_key": _base64url(bytes(key.verify_key)),
            "role": role,
        }
        for role, key in zip(REVIEWER_ROLES, keys, strict=True)
    ]
    descriptor: dict[str, JsonValue] = {
        "schema_version": "1.0",
        "reviewers": reviewers,
    }
    encoded = canonical_bytes(descriptor)
    _ = path.write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest()


def build_info(path: Path, trusted_roots_hash: str) -> str:
    """Write one schema-valid UI identity used as the review subject."""
    schema_hashes: dict[str, JsonValue] = {"ui-build-info": "d" * 64}
    payload: dict[str, JsonValue] = {
        "schema_version": "1.0",
        "service_name": "telco-twin-console",
        "version": "0.1.0",
        "runtime_source_commit_sha": "a" * 40,
        "release_commit_sha": "b" * 40,
        "runtime_tree_hash": "c" * 64,
        "schema_hashes": schema_hashes,
        "mcp_hash": "e" * 64,
        "policy_hash": "f" * 64,
        "trusted_root_hashes": trusted_roots_hash,
        "built_at": "2026-08-29T00:00:00Z",
        "asset_manifest_hash": "1" * 64,
    }
    encoded = canonical_bytes(payload)
    _ = path.write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest()


def _capture_value(capture: CapturePayload) -> dict[str, JsonValue]:
    axe: dict[str, JsonValue] = {
        "serious": capture["axe"]["serious"],
        "critical": capture["axe"]["critical"],
    }
    console: dict[str, JsonValue] = {"errors": capture["console"]["errors"]}
    network: dict[str, JsonValue] = {"unexpected": capture["network"]["unexpected"]}
    return {
        "route": capture["route"],
        "state": capture["state"],
        "viewport": capture["viewport"],
        "path": capture["path"],
        "width": capture["width"],
        "height": capture["height"],
        "sha256": capture["sha256"],
        "captured_at": capture["captured_at"],
        "source_commit_sha": capture["source_commit_sha"],
        "release_commit_sha": capture["release_commit_sha"],
        "build_info_sha256": capture["build_info_sha256"],
        "axe": axe,
        "console": console,
        "network": network,
    }


def _subject_hash(manifest: VisualManifest) -> str:
    captures: list[JsonValue] = [_capture_value(capture) for capture in manifest["captures"]]
    subject: dict[str, JsonValue] = {
        "schema_version": manifest["schema_version"],
        "source_commit_sha": manifest["source_commit_sha"],
        "release_commit_sha": manifest["release_commit_sha"],
        "build_info_sha256": manifest["build_info_sha256"],
        "captures": captures,
    }
    return hashlib.sha256(canonical_bytes(subject)).hexdigest()


def bind_reviewer_receipts(
    manifest_path: Path,
    manifest: VisualManifest,
    *,
    shared_run_id: bool = False,
    shared_key: bool = False,
) -> None:
    """Publish signed approvals and bind their hashes into the manifest."""
    subject = _subject_hash(manifest)
    manifest["subject_sha256"] = subject
    reviewers: list[ReviewerPayload] = []
    keys = signing_keys(shared_key=shared_key)
    for index, (role, key) in enumerate(zip(REVIEWER_ROLES, keys, strict=True), start=1):
        run_id = "review-run-0001" if shared_run_id else f"review-run-000{index}"
        unsigned: dict[str, JsonValue] = {
            "schema_version": "1.0",
            "reviewer_role": role,
            "reviewer_run_id": run_id,
            "key_id": f"{role}-review-root-v1",
            "verdict": "approved",
            "source_commit_sha": manifest["source_commit_sha"],
            "release_commit_sha": manifest["release_commit_sha"],
            "build_info_sha256": manifest["build_info_sha256"],
            "subject_sha256": subject,
        }
        signature = key.sign(REVIEW_DOMAIN + canonical_bytes(unsigned)).signature
        receipt: dict[str, JsonValue] = {
            **unsigned,
            "signature": _base64url(signature),
        }
        relative = Path("reviews") / f"{role}.json"
        receipt_path = manifest_path.parent / relative
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        encoded = canonical_bytes(receipt)
        _ = receipt_path.write_bytes(encoded)
        reviewers.append(
            {
                "role": role,
                "run_id": run_id,
                "receipt_path": relative.as_posix(),
                "receipt_sha256": hashlib.sha256(encoded).hexdigest(),
            }
        )
    manifest["reviewers"] = reviewers
    _ = manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
