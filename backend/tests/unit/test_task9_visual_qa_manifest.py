"""Adversarial Task 9 visual-QA manifest regressions."""
# pyright: reportUnusedCallResult=false, reportUnnecessaryComparison=false

from __future__ import annotations

import hashlib
import json
import os
import struct
import subprocess
import sys
import zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final, Literal, TypedDict, assert_never

import pytest

REPO_ROOT: Final = Path(__file__).resolve().parents[3]
VISUAL_SCRIPT: Final = REPO_ROOT / "scripts/assert_visual_qa_manifest.py"
ROUTES: Final = ("ScenarioWorkbench", "RunDetail", "EvidenceBoard", "BenchmarkLab", "About")
STATES: Final = ("loading", "empty", "error", "stale", "rejected", "approved", "demo")
VIEWPORTS: Final = ("desktop", "mobile")
Mutation = Literal[
    "state",
    "reviewer",
    "path",
    "absolute",
    "console",
    "axe",
    "network",
    "secret",
    "fixture",
]


class CapturePayload(TypedDict, total=False):
    route: str
    state: str
    viewport: str
    path: str
    width: int
    height: int
    captured_at: str
    source_commit_sha: str
    release_commit_sha: str
    build_info_sha256: str
    axe: dict[str, int]
    console: dict[str, int]
    network: dict[str, int]
    note: str


class ReviewerPayload(TypedDict):
    id: str
    approved: bool
    source_commit_sha: str
    release_commit_sha: str
    build_info_sha256: str


class VisualManifest(TypedDict):
    schema_version: str
    source_commit_sha: str
    release_commit_sha: str
    build_info_sha256: str
    captures: list[CapturePayload]
    reviewers: list[ReviewerPayload]


def _run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)


def _png(path: Path, width: int, height: int) -> None:
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    chunk = struct.pack(">I", len(header)) + b"IHDR" + header
    chunk += struct.pack(">I", zlib.crc32(b"IHDR" + header) & 0xFFFFFFFF)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk)


def _build_info(path: Path) -> str:
    payload = {
        "schema_version": "1.0",
        "service_name": "telco-twin-console",
        "version": "0.1.0",
        "runtime_source_commit_sha": "a" * 40,
        "release_commit_sha": "b" * 40,
        "runtime_tree_hash": "c" * 64,
        "schema_hashes": {"ui-build-info": "d" * 64},
        "mcp_hash": "e" * 64,
        "policy_hash": "f" * 64,
        "trusted_root_hashes": "0" * 64,
        "built_at": "2026-08-29T00:00:00Z",
        "asset_manifest_hash": "1" * 64,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    path.write_text(encoded, encoding="utf-8")
    return hashlib.sha256(encoded.encode()).hexdigest()


def _visual_fixture(tmp_path: Path) -> tuple[Path, VisualManifest, datetime]:
    root = tmp_path / "visual"
    root.mkdir()
    build_hash = _build_info(root / "build-info.json")
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
                _png(file_path, width, 800)
                captures.append(
                    {
                        "route": route,
                        "state": state,
                        "viewport": viewport,
                        "path": relative.as_posix(),
                        "width": width,
                        "height": 800,
                        "captured_at": captured_at,
                        "source_commit_sha": "a" * 40,
                        "release_commit_sha": "b" * 40,
                        "build_info_sha256": build_hash,
                        "axe": {"serious": 0, "critical": 0},
                        "console": {"errors": 0},
                        "network": {"unexpected": 0},
                    }
                )
    reviewers: list[ReviewerPayload] = [
        {
            "id": "designer",
            "approved": True,
            "source_commit_sha": "a" * 40,
            "release_commit_sha": "b" * 40,
            "build_info_sha256": build_hash,
        },
        {
            "id": "accessibility",
            "approved": True,
            "source_commit_sha": "a" * 40,
            "release_commit_sha": "b" * 40,
            "build_info_sha256": build_hash,
        },
    ]
    manifest: VisualManifest = {
        "schema_version": "1.0",
        "source_commit_sha": "a" * 40,
        "release_commit_sha": "b" * 40,
        "build_info_sha256": build_hash,
        "captures": captures,
        "reviewers": reviewers,
    }
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    return path, manifest, now


def _assert_visual(
    manifest: Path,
    build_info: Path,
    now: datetime | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(VISUAL_SCRIPT),
        str(manifest),
        "--build-info",
        str(build_info),
        "--max-age-seconds",
        "3600",
    ]
    if now is not None:
        command.extend(("--now", now.strftime("%Y-%m-%dT%H:%M:%SZ")))
    return _run(command, manifest.parent)


def test_visual_manifest_accepts_required_routes_states_and_viewports(tmp_path: Path) -> None:
    # Given: fresh PNG captures and two approving reviewers bound to one build.
    manifest, _, now = _visual_fixture(tmp_path)
    # When: the strict visual-QA assertion runs.
    result = _assert_visual(manifest, manifest.parent / "build-info.json", now)
    # Then: all 70 route/state/viewport captures are accepted.
    assert result.returncode == 0, result.stdout + result.stderr
    assert "visual-qa-manifest-valid captures=70 reviewers=2" in result.stdout


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        ("state", "invalid-state"),
        ("reviewer", "reviewer-mismatch"),
        ("path", "path-traversal"),
        ("absolute", "path-traversal"),
        ("console", "console-errors"),
        ("axe", "axe-violations"),
        ("network", "network-errors"),
        ("secret", "secret-data"),
        ("fixture", "fixture-route"),
    ],
)
def test_visual_manifest_rejects_hostile_variants(
    tmp_path: Path,
    mutation: Mutation,
    error_code: str,
) -> None:
    # Given: a valid manifest changed by one hostile input mutation.
    manifest_path, manifest, now = _visual_fixture(tmp_path)
    match mutation:
        case "state":
            manifest["captures"][0]["state"] = "default"
        case "reviewer":
            manifest["reviewers"][1]["release_commit_sha"] = "c" * 40
        case "path":
            manifest["captures"][0]["path"] = "../escape.png"
        case "absolute":
            manifest["captures"][0]["path"] = str(tmp_path / "escape.png")
        case "console":
            manifest["captures"][0]["console"] = {"errors": 1}
        case "axe":
            manifest["captures"][0]["axe"] = {"serious": 1, "critical": 0}
        case "network":
            manifest["captures"][0]["network"] = {"unexpected": 1}
        case "secret":
            manifest["captures"][0]["note"] = "Bearer secret-value"
        case "fixture":
            manifest["captures"][0]["path"] = "captures/production-fixture.png"
        case unreachable:
            assert_never(unreachable)
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    # When: the manifest is parsed and checked.
    result = _assert_visual(manifest_path, manifest_path.parent / "build-info.json", now)
    # Then: the stable error code rejects the mutation.
    assert result.returncode != 0
    assert f"visual-qa-error:{error_code}:" in result.stderr


def test_visual_manifest_rejects_missing_and_stale_capture_files(tmp_path: Path) -> None:
    # Given: a valid manifest whose first capture is missing and then stale.
    manifest_path, manifest, now = _visual_fixture(tmp_path)
    first_path = manifest["captures"][0].get("path")
    assert isinstance(first_path, str)
    first = manifest_path.parent / first_path
    first.unlink()
    missing = _assert_visual(manifest_path, manifest_path.parent / "build-info.json", now)
    assert missing.returncode != 0
    assert "visual-qa-error:capture-missing:" in missing.stderr
    _png(first, 1280, 800)
    old = (now - timedelta(days=2)).timestamp()
    os.utime(first, (old, old))
    # When: the same manifest is checked after the screenshot ages past the limit.
    stale = _assert_visual(manifest_path, manifest_path.parent / "build-info.json", now)
    # Then: freshness is required for every capture file.
    assert stale.returncode != 0
    assert "visual-qa-error:stale-capture:" in stale.stderr


def test_visual_manifest_rejects_bad_png_signature(tmp_path: Path) -> None:
    # Given: a complete manifest whose first screenshot is not a PNG.
    manifest_path, manifest, now = _visual_fixture(tmp_path)
    first_path = manifest["captures"][0].get("path")
    assert isinstance(first_path, str)
    (manifest_path.parent / first_path).write_bytes(b"not-a-png")
    # When: screenshot bytes are inspected.
    result = _assert_visual(manifest_path, manifest_path.parent / "build-info.json", now)
    # Then: the PNG signature check fails closed.
    assert result.returncode != 0
    assert "visual-qa-error:invalid-png:" in result.stderr


def test_visual_manifest_rejects_declared_dimension_drift(tmp_path: Path) -> None:
    # Given: a valid PNG whose manifest declares the wrong dimensions.
    manifest_path, manifest, now = _visual_fixture(tmp_path)
    manifest["captures"][0]["width"] = 1
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    # When: PNG dimensions are compared to the declaration.
    result = _assert_visual(manifest_path, manifest_path.parent / "build-info.json", now)
    # Then: dimension drift is rejected.
    assert result.returncode != 0
    assert "visual-qa-error:dimensions-mismatch:" in result.stderr
