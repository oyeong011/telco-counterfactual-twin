"""Task 9 visual-QA route, state, diagnostics, and freshness contracts."""
# pyright: reportUnnecessaryComparison=false

from __future__ import annotations

import json
import os
from datetime import timedelta
from typing import TYPE_CHECKING, Literal, assert_never

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from .task9_visual_qa_fixtures import (
    REVIEWER_ROLES,
    ROUTES,
    STATES,
    assert_visual,
    bind_reviewer_receipts,
    visual_fixture,
    write_png,
)

Mutation = Literal[
    "state",
    "path",
    "absolute",
    "console",
    "axe",
    "network",
    "secret",
    "fixture",
]


def test_visual_manifest_accepts_required_routes_states_and_viewports(tmp_path: Path) -> None:
    # Given: fresh complete captures and two external reviewer receipts.
    manifest, _, now = visual_fixture(tmp_path)
    # When: the strict visual-QA assertion runs.
    result = assert_visual(manifest, manifest.parent / "build-info.json", now)
    # Then: all 70 route/state/viewport captures are accepted.
    assert result.returncode == 0, result.stdout + result.stderr
    assert "visual-qa-manifest-valid captures=70 reviewers=2" in result.stdout


def test_visual_manifest_accepts_task9_acceptance_flags(tmp_path: Path) -> None:
    # Given: a valid manifest and the exact Task 9 acceptance option set.
    manifest, _, now = visual_fixture(tmp_path)
    flags = (
        "--require-all-routes",
        "--require-states",
        ",".join(STATES),
        "--viewports",
        "desktop,mobile",
        "--reviewers",
        "2",
    )
    # When: the acceptance command is invoked.
    result = assert_visual(manifest, manifest.parent / "build-info.json", now, flags)
    # Then: all declared requirements are parsed and enforced.
    assert result.returncode == 0, result.stdout + result.stderr


def test_visual_manifest_enforces_requested_subset_cross_product(tmp_path: Path) -> None:
    # Given: only loading/mobile captures across every required route.
    manifest_path, manifest, now = visual_fixture(tmp_path)
    manifest["captures"] = [
        capture
        for capture in manifest["captures"]
        if capture.get("state") == "loading" and capture.get("viewport") == "mobile"
    ]
    bind_reviewer_receipts(manifest_path, manifest)
    # When: the CLI requests that exact route/state/viewport matrix.
    result = assert_visual(
        manifest_path,
        manifest_path.parent / "build-info.json",
        now,
        (
            "--require-all-routes",
            "--require-states",
            "loading",
            "--viewports",
            "mobile",
            "--reviewers",
            "2",
        ),
    )
    # Then: options change the enforced matrix rather than being label-only flags.
    assert result.returncode == 0, result.stdout + result.stderr
    assert "captures=5 reviewers=2" in result.stdout


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        ("state", "invalid-state"),
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
    manifest_path, manifest, now = visual_fixture(tmp_path)
    capture = manifest["captures"][0]
    match mutation:
        case "state":
            capture["state"] = "default"
        case "path":
            capture["path"] = "../escape.png"
        case "absolute":
            capture["path"] = str(tmp_path / "escape.png")
        case "console":
            capture["console"] = {"errors": 1}
        case "axe":
            capture["axe"] = {"serious": 1, "critical": 0}
        case "network":
            capture["network"] = {"unexpected": 1}
        case "secret":
            capture["note"] = "Bearer secret-value"
        case "fixture":
            capture["path"] = "captures/production-fixture.png"
        case unreachable:
            assert_never(unreachable)
    _ = manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    # When: the manifest is parsed and checked.
    result = assert_visual(manifest_path, manifest_path.parent / "build-info.json", now)
    # Then: the stable error code rejects the mutation.
    assert result.returncode != 0
    assert f"visual-qa-error:{error_code}:" in result.stderr


def test_visual_manifest_rejects_missing_and_stale_capture_files(tmp_path: Path) -> None:
    # Given: a valid manifest whose first capture is missing and then stale.
    manifest_path, manifest, now = visual_fixture(tmp_path)
    first_path = manifest["captures"][0].get("path")
    assert isinstance(first_path, str)
    first = manifest_path.parent / first_path
    first.unlink()
    missing = assert_visual(manifest_path, manifest_path.parent / "build-info.json", now)
    assert missing.returncode != 0
    assert "visual-qa-error:capture-missing:" in missing.stderr
    _ = write_png(first, 1280, 800)
    old = (now - timedelta(days=2)).timestamp()
    os.utime(first, (old, old))
    # When: the same manifest is checked after the screenshot ages past the limit.
    stale = assert_visual(manifest_path, manifest_path.parent / "build-info.json", now)
    # Then: freshness is required for every capture file.
    assert stale.returncode != 0
    assert "visual-qa-error:stale-capture:" in stale.stderr


def test_visual_manifest_rejects_declared_dimension_drift(tmp_path: Path) -> None:
    # Given: a valid PNG whose manifest declares the wrong dimensions.
    manifest_path, manifest, now = visual_fixture(tmp_path)
    manifest["captures"][0]["width"] = 1
    _ = manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    # When: PNG dimensions are compared to the declaration.
    result = assert_visual(manifest_path, manifest_path.parent / "build-info.json", now)
    # Then: dimension drift is rejected.
    assert result.returncode != 0
    assert "visual-qa-error:dimensions-mismatch:" in result.stderr


def test_visual_manifest_required_roles_are_stable() -> None:
    # Given/When/Then: the two independent review concerns are explicit machine roles.
    assert REVIEWER_ROLES == ("visual-fidelity", "accessibility")
    assert len(ROUTES) == 5
