#!/usr/bin/env -S uv run --project backend python
# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = []
# ///
# pyright: reportUnusedFunction=false

# ─── How to run ───
# Imported by frontend_build_identity.py; run the wrapper instead.
# ────────────────

"""Deterministic ephemeral Vite build used as the UI asset identity source."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from scripts.frontend_build_support import BuildIdentityError
from scripts.frontend_build_tree import emitted_asset_hash


def _vite_executable(root: Path) -> Path:
    candidate = root / "frontend/node_modules/.bin/vite"
    if not candidate.is_file():
        raise BuildIdentityError("vite-unavailable", candidate.as_posix())
    return candidate


def ephemeral_vite_asset_hash(root: Path, expected_build_info: bytes | None) -> str:
    """Build into a temporary directory and return its emitted-asset hash."""
    vite = _vite_executable(root)
    environment = {**os.environ, "CI": "1", "NODE_ENV": "production"}
    with tempfile.TemporaryDirectory(prefix="telco-twin-vite-") as temporary:
        output = Path(temporary)
        result = subprocess.run(
            [
                str(vite),
                "build",
                "--manifest",
                "--configLoader",
                "runner",
                "--outDir",
                output.as_posix(),
                "--emptyOutDir",
            ],
            cwd=root / "frontend",
            env=environment,
            capture_output=True,
            text=False,
            check=False,
        )
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip()[:400]
            raise BuildIdentityError("vite-build-failed", detail or "vite failed")
        asset_hash = emitted_asset_hash(output, output / ".vite/manifest.json")
        if expected_build_info is not None:
            copied = output / "build-info.json"
            try:
                copied_bytes = copied.read_bytes()
            except OSError as error:
                raise BuildIdentityError(
                    "build-info-copy-missing", copied.as_posix()
                ) from error
            if copied_bytes != expected_build_info:
                raise BuildIdentityError("build-info-copy-mismatch", copied.as_posix())
        return asset_hash
