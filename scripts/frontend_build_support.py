#!/usr/bin/env -S uv run --project backend python
# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["pydantic==2.13.4", "rfc8785>=0.1.4,<0.2"]
# ///
# pyright: reportUnusedFunction=false, reportUnusedParameter=false, reportImplicitOverride=false

# ─── How to run ───
# Imported by frontend_build_identity.py; run the wrapper instead.
# ────────────────

from __future__ import annotations

import hashlib
import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import rfc8785
from pydantic import JsonValue, TypeAdapter, ValidationError

SCHEMA_VERSION: Final = "1.0"
DEFAULT_ROOT: Final = Path(".")
DEFAULT_OUTPUT: Final = Path("frontend/public/build-info.json")
DEFAULT_ASSETS_ROOT: Final = Path("frontend/dist")
DEFAULT_ASSET_MANIFEST: Final = Path(".vite/manifest.json")
DEFAULT_CONTRACT_ROOT: Final = Path("specs/schemas")
DEFAULT_LOCK_PATH: Final = Path("frontend/pnpm-lock.yaml")
DEFAULT_MCP_PATH: Final = Path("artifacts/contracts/mcp.json")
EMPTY_ARTIFACT_HASH: Final = hashlib.sha256(b"{}\n").hexdigest()
SHA1_PATTERN: Final = re.compile(r"[0-9a-f]{40}\Z")
TIMESTAMP_PATTERN: Final = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
JSON_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


def _reject_duplicate_keys(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    keys = tuple(key for key, _ in pairs)
    if len(keys) != len(set(keys)):
        raise BuildIdentityError("invalid-json", "duplicate JSON key")
    return dict(pairs)


@dataclass(frozen=True, slots=True)
class BuildPaths:
    """Repository paths that define the UI identity boundary."""

    root: Path
    output: Path
    assets_root: Path
    asset_manifest: Path
    contract_root: Path
    lock_path: Path
    mcp_path: Path
    trusted_roots_path: Path | None


@dataclass(frozen=True, slots=True)
class BuildIdentityError(Exception):
    """Stable fail-closed error emitted by both generation modes."""

    code: str
    detail: str

    def __str__(self) -> str:
        return f"build-info-error:{self.code}:{self.detail}"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    if path.is_symlink():
        raise BuildIdentityError("path-traversal", path.as_posix())
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as error:
        raise BuildIdentityError("missing-input", path.as_posix()) from error


def _git(root: Path, args: Sequence[str]) -> str:
    return _git_bytes(root, args).decode("utf-8", errors="strict").rstrip("\r\n")


def _git_bytes(root: Path, args: Sequence[str]) -> bytes:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=False, check=False
    )
    if result.returncode != 0:
        detail = (
            result.stderr.decode("utf-8", errors="replace").strip()
            or "git command failed"
        )
        raise BuildIdentityError("git-failure", detail)
    return result.stdout


def _git_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if result.returncode not in {0, 1}:
        raise BuildIdentityError("git-failure", "merge-base failed")
    return result.returncode == 0


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise BuildIdentityError("path-traversal", path.as_posix()) from error


def _repo_cli_path(root: Path, value: Path, field: str) -> Path:
    if value.is_absolute() or "\x00" in value.as_posix() or ".." in value.parts:
        raise BuildIdentityError("path-traversal", field)
    candidate = root / value
    _ = _relative(root, candidate)
    current = root
    for part in value.parts:
        current /= part
        if current.is_symlink():
            raise BuildIdentityError("path-traversal", field)
    return candidate


def _status(root: Path) -> tuple[tuple[str, str], ...]:
    raw = _git(root, ["status", "--porcelain=v1", "-z", "--untracked-files=all"])
    parts = tuple(part for part in raw.split("\0") if part)
    entries: list[tuple[str, str]] = []
    index = 0
    while index < len(parts):
        row = parts[index]
        if len(row) < 4 or row[2] != " ":
            raise BuildIdentityError("git-failure", "malformed status output")
        entries.append((row[:2], row[3:]))
        index += 1
        if "R" in row[:2] or "C" in row[:2]:
            if index >= len(parts):
                raise BuildIdentityError("git-failure", "malformed rename status")
            index += 1
    return tuple(entries)


def _require_clean(root: Path, output: Path, *, check: bool) -> None:
    output_name = _relative(root, output)
    entries = _status(root)
    if check:
        if entries:
            raise BuildIdentityError(
                "dirty-worktree", ",".join(path for _, path in entries)
            )
        tracked = _git(root, ["ls-files", "--error-unmatch", output_name])
        if tracked != output_name:
            raise BuildIdentityError("missing-output", output_name)
        return
    allowed = tuple(
        (status, path)
        for status, path in entries
        if path != output_name or status not in {" M", " D", "??"}
    )
    if allowed:
        raise BuildIdentityError(
            "dirty-worktree", ",".join(path for _, path in allowed)
        )


def _files_under(
    root: Path, directory: Path, *, exclude: frozenset[Path]
) -> tuple[Path, ...]:
    _ = _relative(root, directory)
    if not directory.exists():
        return ()
    if directory.is_symlink():
        raise BuildIdentityError("path-traversal", directory.as_posix())
    files: list[Path] = []
    for path in sorted(directory.rglob("*")):
        if path in exclude:
            continue
        if path.is_symlink():
            raise BuildIdentityError("path-traversal", path.as_posix())
        if path.is_file():
            files.append(path)
    return tuple(files)


def _records_hash(root: Path, files: tuple[Path, ...]) -> str:
    records = b"".join(
        _relative(root, path).encode() + b"\0" + _sha256_file(path).encode() + b"\n"
        for path in files
    )
    return _sha256_bytes(records)


def _schema_hashes(paths: BuildPaths) -> dict[str, JsonValue]:
    files = tuple(sorted(paths.contract_root.glob("*.schema.json")))
    if not files:
        raise BuildIdentityError(
            "missing-input", _relative(paths.root, paths.contract_root)
        )
    if any(path.is_symlink() for path in files):
        linked = next(path for path in files if path.is_symlink())
        raise BuildIdentityError("path-traversal", _relative(paths.root, linked))
    hashes: dict[str, JsonValue] = {}
    for path in files:
        if path.is_file():
            hashes[path.name.removesuffix(".schema.json")] = _sha256_file(path)
    return hashes


def _canonical_file_hash(path: Path | None, default: str) -> str:
    if path is None or not path.exists():
        return default
    if not path.is_file() or path.is_symlink():
        raise BuildIdentityError("missing-input", path.as_posix())
    try:
        parsed = JSON_ADAPTER.validate_json(path.read_bytes())
    except (OSError, ValueError, ValidationError) as error:
        raise BuildIdentityError("invalid-json", path.as_posix()) from error
    return _sha256_bytes(rfc8785.dumps(parsed) + b"\n")


def _timestamp(root: Path, value: str | None) -> str:
    candidate = value or _git(root, ["show", "-s", "--format=%cI", "HEAD"])
    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError as error:
        raise BuildIdentityError("invalid-timestamp", candidate) from error
    if parsed.tzinfo is None:
        raise BuildIdentityError("invalid-timestamp", candidate)
    normalized = parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not TIMESTAMP_PATTERN.fullmatch(normalized):
        raise BuildIdentityError("invalid-timestamp", candidate)
    return normalized


def _sha_argument(value: str, name: str) -> str:
    if not SHA1_PATTERN.fullmatch(value):
        raise BuildIdentityError("invalid-commit", name)
    return value
