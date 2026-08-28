"""Realistic evidence fixtures for Task 9 visual-QA CLI tests."""

from __future__ import annotations

import hashlib
import json
import struct
import subprocess
import sys
import zlib
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final, NotRequired, TypedDict

import rfc8785

if TYPE_CHECKING:
    from pydantic import JsonValue

REPO_ROOT: Final = Path(__file__).resolve().parents[3]
VISUAL_SCRIPT: Final = REPO_ROOT / "scripts/assert_visual_qa_manifest.py"
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


def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run the real visual assertion CLI and capture its result."""
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)


def canonical_bytes(value: JsonValue) -> bytes:
    """Encode one evidence object with the same public RFC8785 contract."""
    return rfc8785.dumps(value) + b"\n"


def png_bytes(width: int, height: int) -> bytes:
    """Create a complete, CRC-valid, zlib-decodable grayscale PNG."""
    header = struct.pack(">IIBBBBB", width, height, 1, 0, 0, 0, 0)
    row = b"\x00" + bytes((width + 7) // 8)

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )


def write_png(path: Path, width: int, height: int) -> str:
    """Write a complete PNG and return its content SHA-256."""
    encoded = png_bytes(width, height)
    _ = path.write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest()


def build_info(path: Path) -> str:
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
        "trusted_root_hashes": "0" * 64,
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


def subject_hash(manifest: VisualManifest) -> str:
    """Bind reviewer receipts to identities and every capture metadata/hash record."""
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
    manifest_path: Path, manifest: VisualManifest, *, shared_run_id: bool = False
) -> None:
    """Publish external approval receipts and bind their hashes into the manifest."""
    subject = subject_hash(manifest)
    manifest["subject_sha256"] = subject
    reviewers: list[ReviewerPayload] = []
    for index, role in enumerate(REVIEWER_ROLES, start=1):
        run_id = "review-run-0001" if shared_run_id else f"review-run-000{index}"
        receipt: dict[str, JsonValue] = {
            "schema_version": "1.0",
            "reviewer_role": role,
            "reviewer_run_id": run_id,
            "verdict": "approved",
            "source_commit_sha": manifest["source_commit_sha"],
            "release_commit_sha": manifest["release_commit_sha"],
            "build_info_sha256": manifest["build_info_sha256"],
            "subject_sha256": subject,
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


def visual_fixture(
    tmp_path: Path, *, shared_run_id: bool = False
) -> tuple[Path, VisualManifest, datetime]:
    """Create a complete route/state/viewport matrix plus review receipts."""
    root = tmp_path / "visual"
    root.mkdir()
    build_hash = build_info(root / "build-info.json")
    now = datetime.now(UTC).replace(microsecond=0)
    captured_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    captures: list[CapturePayload] = []
    for route in ROUTES:
        for state in STATES:
            for viewport in VIEWPORTS:
                relative = Path("captures") / route / state / f"{viewport}.png"
                file_path = root / relative
                file_path.parent.mkdir(parents=True, exist_ok=True)
                width = 1280 if viewport == "desktop" else 390
                captures.append(
                    {
                        "route": route,
                        "state": state,
                        "viewport": viewport,
                        "path": relative.as_posix(),
                        "width": width,
                        "height": 800,
                        "sha256": write_png(file_path, width, 800),
                        "captured_at": captured_at,
                        "source_commit_sha": "a" * 40,
                        "release_commit_sha": "b" * 40,
                        "build_info_sha256": build_hash,
                        "axe": {"serious": 0, "critical": 0},
                        "console": {"errors": 0},
                        "network": {"unexpected": 0},
                    }
                )
    manifest: VisualManifest = {
        "schema_version": "1.0",
        "source_commit_sha": "a" * 40,
        "release_commit_sha": "b" * 40,
        "build_info_sha256": build_hash,
        "subject_sha256": "0" * 64,
        "captures": captures,
        "reviewers": [],
    }
    path = root / "manifest.json"
    bind_reviewer_receipts(path, manifest, shared_run_id=shared_run_id)
    return path, manifest, now


def assert_visual(
    manifest: Path,
    build_info_path: Path,
    now: datetime | None = None,
    extra: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    """Invoke the real assertion command with deterministic freshness controls."""
    command = [
        sys.executable,
        str(VISUAL_SCRIPT),
        str(manifest),
        "--build-info",
        str(build_info_path),
        "--max-age-seconds",
        "3600",
        *extra,
    ]
    if now is not None:
        command.extend(("--now", now.strftime("%Y-%m-%dT%H:%M:%SZ")))
    return run(command, manifest.parent)
