"""Realistic evidence fixtures for Task 9 visual-QA CLI tests."""

from __future__ import annotations

import hashlib
import struct
import subprocess
import sys
import zlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from .task9_visual_review_fixtures import (
    CapturePayload,
    VisualManifest,
    bind_reviewer_receipts,
    build_info,
    reviewer_trust,
)

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


def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run the real visual assertion CLI and capture its result."""
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)


def png_chunk(kind: bytes, data: bytes) -> bytes:
    """Encode one CRC-bound PNG chunk."""
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))


def png_bytes(width: int, height: int) -> bytes:
    """Create a complete, CRC-valid, zlib-decodable grayscale PNG."""
    header = struct.pack(">IIBBBBB", width, height, 1, 0, 0, 0, 0)
    row = b"\x00" + bytes((width + 7) // 8)
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", header)
        + png_chunk(b"IDAT", zlib.compress(row * height))
        + png_chunk(b"IEND", b"")
    )


def palette_png_bytes(width: int, height: int, *, include_plte: bool) -> bytes:
    """Create an indexed PNG with an optional required palette chunk."""
    header = struct.pack(">IIBBBBB", width, height, 8, 3, 0, 0, 0)
    row = b"\x00" + bytes(width)
    palette = png_chunk(b"PLTE", b"\x00\x00\x00") if include_plte else b""
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", header)
        + palette
        + png_chunk(b"IDAT", zlib.compress(row * height))
        + png_chunk(b"IEND", b"")
    )


def unknown_critical_png_bytes(width: int, height: int) -> bytes:
    """Create a PNG containing an unknown critical ABCD chunk."""
    encoded = png_bytes(width, height)
    return encoded[:33] + png_chunk(b"ABCD", b"") + encoded[33:]


def nonconsecutive_idat_png_bytes(width: int, height: int) -> bytes:
    """Create a PNG whose IDAT sequence is interrupted by an ancillary chunk."""
    header = struct.pack(">IIBBBBB", width, height, 1, 0, 0, 0, 0)
    row = b"\x00" + bytes((width + 7) // 8)
    compressed = zlib.compress(row * height)
    middle = len(compressed) // 2
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", header)
        + png_chunk(b"IDAT", compressed[:middle])
        + png_chunk(b"tEXt", b"note\x00split")
        + png_chunk(b"IDAT", compressed[middle:])
        + png_chunk(b"IEND", b"")
    )


def write_png(path: Path, width: int, height: int) -> str:
    """Write a complete PNG and return its content SHA-256."""
    encoded = png_bytes(width, height)
    _ = path.write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest()


def visual_fixture(
    tmp_path: Path, *, shared_run_id: bool = False, shared_key: bool = False
) -> tuple[Path, VisualManifest, datetime]:
    """Create a complete route/state/viewport matrix plus review receipts."""
    root = tmp_path / "visual"
    root.mkdir()
    trust_hash = reviewer_trust(root / "reviewer-trust.json", shared_key=shared_key)
    build_hash = build_info(root / "build-info.json", trust_hash)
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
    bind_reviewer_receipts(path, manifest, shared_run_id=shared_run_id, shared_key=shared_key)
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
        build_info_path.relative_to(manifest.parent).as_posix(),
        "--repo-root",
        str(manifest.parent),
        "--reviewer-trust-descriptor",
        "reviewer-trust.json",
        "--max-age-seconds",
        "3600",
        *extra,
    ]
    if now is not None:
        command.extend(("--now", now.strftime("%Y-%m-%dT%H:%M:%SZ")))
    return run(command, manifest.parent)
