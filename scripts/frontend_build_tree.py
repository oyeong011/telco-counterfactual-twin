#!/usr/bin/env -S uv run --project backend python
# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["pydantic==2.13.4"]
# ///
# pyright: reportPrivateUsage=false, reportUnusedFunction=false

# ─── How to run ───
# Imported by frontend_build_identity.py; run the wrapper instead.
# ────────────────

"""Canonical runtime-tree and emitted-asset identity calculations."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Final

from pydantic import JsonValue, ValidationError

from scripts import frontend_build_support as support
from scripts.frontend_build_support import BuildIdentityError

FIXED_RUNTIME_PATHS: Final = (
    "frontend/package.json",
    "frontend/pnpm-lock.yaml",
    "frontend/pnpm-workspace.yaml",
)
ASSET_REFERENCE_FIELDS: Final = ("css", "assets")


def _is_runtime_path(path: str) -> bool:
    candidate = Path(path)
    return (
        path in FIXED_RUNTIME_PATHS
        or path.startswith(("frontend/src/", "specs/schemas/"))
        or (
            candidate.parent.as_posix() == "frontend"
            and candidate.name.startswith("tsconfig")
            and candidate.suffix == ".json"
        )
    )


def _require_runtime_shape(paths: tuple[str, ...]) -> None:
    path_set = set(paths)
    missing = tuple(path for path in FIXED_RUNTIME_PATHS if path not in path_set)
    if missing or not any(path.startswith("frontend/src/") for path in paths):
        raise BuildIdentityError("missing-input", ",".join(missing) or "frontend/src")
    if not any(path.startswith("specs/schemas/") for path in paths):
        raise BuildIdentityError("missing-input", "specs/schemas")


def runtime_files(root: Path) -> tuple[Path, ...]:
    """Expand the exact Twin UI component path set declared by the plan."""
    frontend = root / "frontend"
    fixed = tuple(root / path for path in FIXED_RUNTIME_PATHS)
    source = support._files_under(root, frontend / "src", exclude=frozenset())
    configs = tuple(sorted(frontend.glob("tsconfig*.json")))
    schemas = support._files_under(root, root / "specs/schemas", exclude=frozenset())
    files = (*fixed, *source, *configs, *schemas)
    for path in files:
        if path.is_symlink():
            raise BuildIdentityError("path-traversal", support._relative(root, path))
        if not path.is_file():
            raise BuildIdentityError("missing-input", support._relative(root, path))
    result = tuple(sorted(set(files), key=lambda path: support._relative(root, path)))
    _require_runtime_shape(tuple(support._relative(root, path) for path in result))
    return result


def current_runtime_hash(root: Path) -> str:
    """Hash the current filesystem's canonical Twin UI runtime tree."""
    return support._records_hash(root, runtime_files(root))


def commit_runtime_hash(root: Path, commit: str) -> str:
    """Hash the same canonical path set from one exact Git commit tree."""
    raw = support._git_bytes(
        root,
        ["ls-tree", "-r", "-z", commit, "--", "frontend", "specs/schemas"],
    )
    records: list[tuple[str, str]] = []
    for entry in tuple(item for item in raw.split(b"\0") if item):
        try:
            metadata, encoded_path = entry.split(b"\t", maxsplit=1)
            mode, kind, object_id = metadata.decode("ascii").split(" ")
            path = encoded_path.decode("utf-8", errors="strict")
        except (UnicodeDecodeError, ValueError) as error:
            raise BuildIdentityError(
                "git-failure", "malformed ls-tree output"
            ) from error
        if not _is_runtime_path(path):
            continue
        if mode == "120000" or kind != "blob":
            raise BuildIdentityError("path-traversal", path)
        digest = hashlib.sha256(
            support._git_bytes(root, ["cat-file", "blob", object_id])
        ).hexdigest()
        records.append((path, digest))
    records.sort()
    _require_runtime_shape(tuple(path for path, _ in records))
    encoded = b"".join(
        path.encode() + b"\0" + digest.encode() + b"\n" for path, digest in records
    )
    return hashlib.sha256(encoded).hexdigest()


def _asset_reference(assets_root: Path, value: JsonValue) -> Path:
    if not isinstance(value, str) or not value:
        raise BuildIdentityError("asset-manifest-invalid", "asset reference")
    return support._repo_cli_path(assets_root, Path(value), "asset reference")


def _manifest_references(assets_root: Path, asset_manifest: Path) -> frozenset[Path]:
    if not asset_manifest.is_file() or asset_manifest.is_symlink():
        raise BuildIdentityError(
            "asset-manifest-missing",
            support._relative(assets_root, asset_manifest),
        )
    try:
        parsed = support.JSON_ADAPTER.validate_python(
            json.loads(
                asset_manifest.read_bytes(),
                object_pairs_hook=support._reject_duplicate_keys,
            )
        )
    except (OSError, ValueError, ValidationError) as error:
        raise BuildIdentityError("asset-manifest-invalid", "invalid JSON") from error
    if not isinstance(parsed, dict) or not parsed:
        raise BuildIdentityError("asset-manifest-invalid", "manifest object")
    references: set[Path] = set()
    for entry in parsed.values():
        if not isinstance(entry, dict):
            raise BuildIdentityError("asset-manifest-invalid", "manifest entry")
        references.add(_asset_reference(assets_root, entry.get("file")))
        for field in ASSET_REFERENCE_FIELDS:
            values = entry.get(field, [])
            if not isinstance(values, list):
                raise BuildIdentityError("asset-manifest-invalid", field)
            references.update(_asset_reference(assets_root, value) for value in values)
    for path in references:
        if not path.is_file() or path.is_symlink():
            raise BuildIdentityError(
                "asset-manifest-missing", support._relative(assets_root, path)
            )
    return frozenset(references)


def emitted_asset_hash(assets_root: Path, asset_manifest: Path) -> str:
    """Bind actual Vite output bytes while excluding self-referential manifests."""
    references = _manifest_references(assets_root, asset_manifest)
    excluded = frozenset(
        {
            asset_manifest,
            assets_root / "build-info.json",
        }
    )
    files = support._files_under(assets_root, assets_root, exclude=excluded)
    if not files or not references.issubset(files):
        raise BuildIdentityError("asset-manifest-invalid", "emitted asset set")
    return support._records_hash(assets_root, files)
