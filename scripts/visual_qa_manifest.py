#!/usr/bin/env -S uv run --project backend python
# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["pydantic==2.13.4", "typer>=0.21,<1"]
# ///
# pyright: reportPrivateUsage=false, reportCallInDefaultInitializer=false

# ─── How to run ───
# Imported by assert_visual_qa_manifest.py; run the wrapper instead.
# ────────────────

"""Parser and assertions for the strict Task 9 visual-QA manifest."""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Final

import typer
from pydantic import JsonValue

from scripts import visual_qa_types as types
from scripts.visual_qa_checks import assert_manifest
from scripts.visual_qa_cli_support import csv_requirement, parse_now, repo_path
from scripts.visual_qa_types import (
    Capture,
    Manifest,
    Reviewer,
    VisualQaError,
    VisualRequirements,
    _integer,
    _mapping,
    _read_json,
    _required,
    _scan_untrusted,
    _sha,
    _sha256,
    _string,
    _timestamp,
)

DEFAULT_BUILD_INFO: Final = Path("frontend/public/build-info.json")
DEFAULT_REVIEWER_TRUST: Final = Path("specs/schemas/visual-qa-reviewers-trust")


def _capture(value: JsonValue, index: int) -> Capture:
    if not isinstance(value, dict):
        raise VisualQaError("schema-mismatch", f"captures[{index}]")
    required = (
        "route",
        "state",
        "viewport",
        "path",
        "width",
        "height",
        "sha256",
        "captured_at",
        "source_commit_sha",
        "release_commit_sha",
        "build_info_sha256",
        "axe",
        "console",
        "network",
    )
    _required(value, required, required, f"captures[{index}]")
    axe = _mapping(value, "axe", f"captures[{index}]")
    console = _mapping(value, "console", f"captures[{index}]")
    network = _mapping(value, "network", f"captures[{index}]")
    _required(axe, ("serious", "critical"), ("serious", "critical"), "axe")
    _required(console, ("errors",), ("errors",), "console")
    _required(network, ("unexpected",), ("unexpected",), "network")
    route = _string(value, "route", f"captures[{index}]")
    state = _string(value, "state", f"captures[{index}]")
    viewport = _string(value, "viewport", f"captures[{index}]")
    if route not in types.ROUTES:
        raise VisualQaError("invalid-route", route)
    if state not in types.STATES:
        raise VisualQaError("invalid-state", state)
    if viewport not in types.VIEWPORTS:
        raise VisualQaError("invalid-viewport", viewport)
    width = _integer(value, "width", f"captures[{index}]")
    height = _integer(value, "height", f"captures[{index}]")
    if width < 1 or height < 1:
        raise VisualQaError("invalid-dimensions", f"captures[{index}]")
    return Capture(
        route=route,
        state=state,
        viewport=viewport,
        path=_string(value, "path", f"captures[{index}]"),
        width=width,
        height=height,
        sha256=_sha256(_string(value, "sha256", f"captures[{index}]"), "sha256"),
        captured_at=_timestamp(
            _string(value, "captured_at", f"captures[{index}]"),
            f"captures[{index}].captured_at",
        ),
        source_sha=_sha(
            _string(value, "source_commit_sha", f"captures[{index}]"),
            "source_commit_sha",
        ),
        release_sha=_sha(
            _string(value, "release_commit_sha", f"captures[{index}]"),
            "release_commit_sha",
        ),
        build_info_sha=_sha256(
            _string(value, "build_info_sha256", f"captures[{index}]"),
            "build_info_sha256",
        ),
        axe_serious=_integer(axe, "serious", "axe"),
        axe_critical=_integer(axe, "critical", "axe"),
        console_errors=_integer(console, "errors", "console"),
        network_unexpected=_integer(network, "unexpected", "network"),
    )


def _reviewer(value: JsonValue, index: int) -> Reviewer:
    if not isinstance(value, dict):
        raise VisualQaError("schema-mismatch", f"reviewers[{index}]")
    required = (
        "role",
        "run_id",
        "receipt_path",
        "receipt_sha256",
    )
    _required(value, required, required, f"reviewers[{index}]")
    role = _string(value, "role", f"reviewers[{index}]")
    run_id = _string(value, "run_id", f"reviewers[{index}]")
    if not re.fullmatch(r"[a-z][a-z0-9-]{7,95}", run_id):
        raise VisualQaError("reviewer-invalid", run_id)
    return Reviewer(
        role=role,
        run_id=run_id,
        receipt_path=_string(value, "receipt_path", f"reviewers[{index}]"),
        receipt_sha=_sha256(
            _string(value, "receipt_sha256", f"reviewers[{index}]"),
            "receipt_sha256",
        ),
    )


def parse_manifest(path: Path) -> Manifest:
    """Parse one strict manifest before any filesystem assertions run."""
    value = _read_json(path)
    _scan_untrusted(value)
    if not isinstance(value, dict):
        raise VisualQaError("schema-mismatch", "manifest must be an object")
    required = (
        "schema_version",
        "source_commit_sha",
        "release_commit_sha",
        "build_info_sha256",
        "subject_sha256",
        "captures",
        "reviewers",
    )
    _required(value, required, required, "manifest")
    if _string(value, "schema_version", "manifest") != types.SCHEMA_VERSION:
        raise VisualQaError("schema-mismatch", "schema_version")
    captures_value = value.get("captures")
    reviewers_value = value.get("reviewers")
    if not isinstance(captures_value, list) or not isinstance(reviewers_value, list):
        raise VisualQaError("schema-mismatch", "captures/reviewers")
    return Manifest(
        source_sha=_sha(
            _string(value, "source_commit_sha", "manifest"), "source_commit_sha"
        ),
        release_sha=_sha(
            _string(value, "release_commit_sha", "manifest"), "release_commit_sha"
        ),
        build_info_sha=_sha256(
            _string(value, "build_info_sha256", "manifest"), "build_info_sha256"
        ),
        subject_sha=_sha256(
            _string(value, "subject_sha256", "manifest"), "subject_sha256"
        ),
        captures=tuple(
            _capture(item, index) for index, item in enumerate(captures_value)
        ),
        reviewers=tuple(
            _reviewer(item, index) for index, item in enumerate(reviewers_value)
        ),
    )


def main(
    manifest: Annotated[
        Path | None, typer.Argument(exists=True, dir_okay=False)
    ] = None,
    manifest_option: Annotated[Path | None, typer.Option("--manifest")] = None,
    build_info: Annotated[Path, typer.Option("--build-info")] = DEFAULT_BUILD_INFO,
    repo_root: Annotated[
        Path, typer.Option("--repo-root", exists=True, file_okay=False)
    ] = Path("."),
    reviewer_trust_descriptor: Annotated[
        Path, typer.Option("--reviewer-trust-descriptor")
    ] = DEFAULT_REVIEWER_TRUST,
    root: Annotated[Path | None, typer.Option("--root")] = None,
    max_age_seconds: Annotated[int, typer.Option("--max-age-seconds", min=1)] = 86400,
    now: Annotated[str | None, typer.Option("--now")] = None,
    require_all_routes: Annotated[bool, typer.Option("--require-all-routes")] = False,
    require_states: Annotated[str | None, typer.Option("--require-states")] = None,
    viewports: Annotated[str | None, typer.Option("--viewports")] = None,
    reviewers: Annotated[int, typer.Option("--reviewers", min=1, max=2)] = 2,
) -> None:
    """Assert the strict Task 9 visual-QA manifest."""
    target = manifest_option or manifest
    if target is None:
        typer.echo("visual-qa-error:manifest-missing:manifest", err=True)
        raise typer.Exit(code=3)
    try:
        parsed = parse_manifest(target)
        resolved_repo = repo_root.resolve()
        requirements = VisualRequirements(
            routes=types.ROUTES
            if require_all_routes
            else tuple(sorted({capture.route for capture in parsed.captures})),
            states=csv_requirement(require_states, types.STATES, "states"),
            viewports=csv_requirement(viewports, types.VIEWPORTS, "viewports"),
            reviewer_count=reviewers,
        )
        assert_manifest(
            parsed,
            repo_path(resolved_repo, build_info, "build_info"),
            (root or target.parent).resolve(),
            now=parse_now(now),
            max_age=timedelta(seconds=max_age_seconds),
            requirements=requirements,
            reviewer_trust_path=repo_path(
                resolved_repo,
                reviewer_trust_descriptor,
                "reviewer_trust_descriptor",
            ),
        )
    except VisualQaError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=3) from error
    typer.echo(
        f"visual-qa-manifest-valid captures={len(parsed.captures)} reviewers={len(parsed.reviewers)}"
    )


if __name__ == "__main__":
    typer.run(main)
