#!/usr/bin/env -S uv run --project backend python
# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = []
# ///

# ─── How to run ───
# 1. Install uv (if not installed):
#      curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Verify cache without network:
#      uv run --project backend python scripts/download_recorded_model.py --verify-only
# 3. Acquire the exact pinned revision explicitly:
#      uv run --project backend python scripts/download_recorded_model.py
# ──────────────────

"""Acquire one exact recorded-model revision into an atomic local cache."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Final, override

import typer
from telco_twin.eval.model_replay import (
    model_cache_directory,
    verify_model_snapshot,
)
from telco_twin.eval.model_replay_contracts import ModelSnapshotError
from telco_twin.eval.recorded_model_baseline import (
    ModelManifestError,
    load_model_manifest,
)

REPO_ROOT: Final = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST: Final = REPO_ROOT / "backend/fixtures/eval/model-manifest-v1.json"
DEFAULT_CACHE: Final = REPO_ROOT / ".cache/recorded-model"


@dataclass(frozen=True, slots=True)
class AcquisitionError(Exception):
    """Downloaded bytes or existing cache failed exact identity checks."""

    detail: str

    @override
    def __str__(self) -> str:
        return f"recorded-model-invalid: {self.detail}"


def main(
    manifest_path: Annotated[Path, typer.Option("--manifest")] = DEFAULT_MANIFEST,
    cache_root: Annotated[Path, typer.Option("--cache-dir")] = DEFAULT_CACHE,
    verify_only: Annotated[bool, typer.Option()] = False,
) -> None:
    """Verify existing cache first, then optionally call exact `hf download --revision`."""
    try:
        manifest = load_model_manifest(manifest_path)
        destination = model_cache_directory(cache_root, manifest.revision)
        if destination.exists():
            try:
                snapshot_hash = verify_model_snapshot(
                    destination, manifest.snapshot_files
                )
            except ModelSnapshotError as error:
                raise AcquisitionError(error.detail) from error
            typer.echo(
                f"model-cache: ready revision={manifest.revision} snapshot={snapshot_hash}"
            )
            return
        if verify_only:
            typer.echo("model-cache: not_run reason=exact-model-cache-missing")
            return
        hf_binary = shutil.which("hf")
        if hf_binary is None:
            typer.echo("model-cache: not_run reason=hf-cli-missing")
            return
        cache_root.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        environment["HF_HUB_DISABLE_TELEMETRY"] = "1"
        with tempfile.TemporaryDirectory(
            prefix=".recorded-model-", dir=cache_root
        ) as temporary:
            staging = Path(temporary)
            try:
                completed = subprocess.run(
                    (
                        hf_binary,
                        "download",
                        manifest.model_id,
                        "--revision",
                        manifest.revision,
                        "--local-dir",
                        str(staging),
                    ),
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=900,
                    env=environment,
                )
            except subprocess.TimeoutExpired:
                typer.echo("model-cache: not_run reason=network-timeout")
                return
            if completed.returncode != 0:
                typer.echo("model-cache: not_run reason=network-or-cache-unavailable")
                return
            try:
                snapshot_hash = verify_model_snapshot(staging, manifest.snapshot_files)
            except ModelSnapshotError as error:
                raise AcquisitionError(error.detail) from error
            _ = staging.replace(destination)
        typer.echo(
            f"model-cache: ready revision={manifest.revision} snapshot={snapshot_hash}"
        )
    except (AcquisitionError, ModelManifestError, OSError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=3) from error


if __name__ == "__main__":
    typer.run(main)
