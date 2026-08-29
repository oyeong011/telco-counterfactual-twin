#!/usr/bin/env -S uv run --project backend python
# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["pydantic==2.13.4", "rfc8785>=0.1.4,<0.2", "typer>=0.21,<1"]
# ///
# pyright: reportPrivateUsage=false, reportUnusedCallResult=false

# ─── How to run ───
# Imported by generate_frontend_build_info.py; run the wrapper instead.
# ────────────────

"""Implementation for the frontend build-info CLI."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Annotated

import rfc8785
import typer
from pydantic import JsonValue, ValidationError
from telco_twin.domain.build_info import UiBuildInfo
from telco_twin.safety.local_policy import LOCAL_POLICY_DEFINITION_HASH

from scripts import frontend_build_support as support
from scripts.frontend_build_support import (
    BuildClaims,
    BuildIdentityError,
    BuildPaths,
    _canonical_file_hash,
    _git,
    _git_ancestor,
    _reject_duplicate_keys,
    _repo_cli_path,
    _require_clean,
    _schema_hashes,
    _sha256_bytes,
    _sha256_file,
    _sha_argument,
    _timestamp,
)
from scripts.frontend_build_tree import (
    commit_runtime_hash,
    current_runtime_hash,
)
from scripts.frontend_vite_build import ephemeral_vite_asset_hash


def _payload(paths: BuildPaths, claims: BuildClaims) -> dict[str, JsonValue]:
    schema_hashes = _schema_hashes(paths)
    if not paths.trusted_roots_path.is_file():
        raise BuildIdentityError("missing-input", paths.trusted_roots_path.as_posix())
    lock_hash = _sha256_file(paths.lock_path)
    contract_hash = _sha256_bytes(rfc8785.dumps(schema_hashes))
    extensions: dict[str, JsonValue] = {
        "schema_version": support.SCHEMA_VERSION,
        "values": {
            "frontend_lock_hash": lock_hash,
            "frontend_assets_hash": claims.asset_hash,
            "contract_manifest_hash": contract_hash,
        },
    }
    return {
        "schema_version": support.SCHEMA_VERSION,
        "service_name": "telco-twin-console",
        "version": "0.1.0",
        "runtime_source_commit_sha": claims.source_sha,
        "release_commit_sha": claims.release_sha,
        "runtime_tree_hash": current_runtime_hash(paths.root),
        "schema_hashes": schema_hashes,
        "mcp_hash": _canonical_file_hash(paths.mcp_path, support.EMPTY_ARTIFACT_HASH),
        "policy_hash": LOCAL_POLICY_DEFINITION_HASH,
        "trusted_root_hashes": _canonical_file_hash(
            paths.trusted_roots_path, support.EMPTY_ARTIFACT_HASH
        ),
        "built_at": claims.built_at,
        "asset_manifest_hash": claims.asset_hash,
        "extensions": extensions,
    }


def _read_payload(path: Path) -> tuple[dict[str, JsonValue], bytes]:
    try:
        raw = path.read_bytes()
        decoded = support.JSON_ADAPTER.validate_python(
            json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
        )
    except (OSError, ValueError, ValidationError) as error:
        raise BuildIdentityError("invalid-json", path.as_posix()) from error
    if not isinstance(decoded, dict):
        raise BuildIdentityError("schema-mismatch", "build-info must be an object")
    if "image_digest" in decoded:
        raise BuildIdentityError("schema-mismatch", "image_digest is forbidden for UI")
    try:
        _ = UiBuildInfo.model_validate(decoded)
    except ValidationError as error:
        raise BuildIdentityError(
            "schema-mismatch", str(error).splitlines()[0]
        ) from error
    return decoded, raw


def _compare_identity(
    actual: dict[str, JsonValue], expected: dict[str, JsonValue]
) -> None:
    for field, value in expected.items():
        if field in {"runtime_source_commit_sha", "release_commit_sha", "built_at"}:
            continue
        if actual.get(field) != value:
            raise BuildIdentityError("hash-mismatch", field)


def _commit_tree_matches(root: Path, commit: str, runtime_hash: str) -> bool:
    try:
        return commit_runtime_hash(root, commit) == runtime_hash
    except BuildIdentityError as error:
        if error.code == "missing-input":
            return False
        raise


def _atomic_write(path: Path, encoded: bytes) -> None:
    """Publish one file atomically from a same-directory fsynced staging file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    staging: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as stream:
            staging = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staging, path)
    except OSError as error:
        if staging is not None:
            staging.unlink(missing_ok=True)
        raise BuildIdentityError("output-write", path.as_posix()) from error


def generate(
    paths: BuildPaths,
    *,
    check: bool,
    source_sha: str | None,
    release_sha: str | None,
    built_at: str | None,
) -> None:
    """Generate one canonical UI identity or validate the checked-in identity."""
    head = _sha_argument(_git(paths.root, ["rev-parse", "HEAD"]), "HEAD")
    parsed = _read_payload(paths.output) if check else None
    if check:
        assert parsed is not None
        actual, actual_bytes = parsed
        actual_source = actual.get("runtime_source_commit_sha")
        actual_release = actual.get("release_commit_sha")
        actual_built_at = actual.get("built_at")
        if not isinstance(actual_source, str):
            raise BuildIdentityError(
                "schema-mismatch", "runtime_source_commit_sha must be a string"
            )
        if not isinstance(actual_release, str):
            raise BuildIdentityError(
                "schema-mismatch", "release_commit_sha must be a string"
            )
        if not isinstance(actual_built_at, str):
            raise BuildIdentityError("schema-mismatch", "built_at must be a string")
        source = _sha_argument(actual_source, "runtime_source_commit_sha")
        release = _sha_argument(actual_release, "release_commit_sha")
        if not _git_ancestor(paths.root, source, head) or not _git_ancestor(
            paths.root, release, head
        ):
            raise BuildIdentityError("source-commit-mismatch", source)
        runtime_hash = current_runtime_hash(paths.root)
        if not _commit_tree_matches(paths.root, source, runtime_hash):
            raise BuildIdentityError("source-commit-mismatch", source)
        if not _commit_tree_matches(paths.root, release, runtime_hash):
            raise BuildIdentityError("release-commit-mismatch", release)
        asset_hash = ephemeral_vite_asset_hash(paths.root, actual_bytes)
        expected = _payload(
            paths,
            BuildClaims(
                source_sha=source,
                release_sha=release,
                built_at=actual_built_at,
                asset_hash=asset_hash,
            ),
        )
        _compare_identity(actual, expected)
        canonical = rfc8785.dumps(actual) + b"\n"
        if actual_bytes != canonical:
            raise BuildIdentityError("canonical-json-mismatch", paths.output.as_posix())
        _require_clean(paths.root, paths.output, check=True)
        return
    _require_clean(paths.root, paths.output, check=False)
    source = _sha_argument(source_sha or head, "runtime_source_commit_sha")
    release = _sha_argument(release_sha or head, "release_commit_sha")
    if not _git_ancestor(paths.root, source, head) or not _git_ancestor(
        paths.root, release, head
    ):
        raise BuildIdentityError("source-commit-mismatch", source)
    runtime_hash = current_runtime_hash(paths.root)
    if not _commit_tree_matches(paths.root, source, runtime_hash):
        raise BuildIdentityError("source-commit-mismatch", source)
    if not _commit_tree_matches(paths.root, release, runtime_hash):
        raise BuildIdentityError("release-commit-mismatch", release)
    asset_hash = ephemeral_vite_asset_hash(paths.root, None)
    payload = _payload(
        paths,
        BuildClaims(
            source_sha=source,
            release_sha=release,
            built_at=_timestamp(paths.root, built_at),
            asset_hash=asset_hash,
        ),
    )
    encoded = rfc8785.dumps(payload) + b"\n"
    _atomic_write(paths.output, encoded)


def main(
    output: Annotated[Path, typer.Argument()] = support.DEFAULT_OUTPUT,
    root: Annotated[
        Path, typer.Option(exists=True, file_okay=False)
    ] = support.DEFAULT_ROOT,
    check: Annotated[bool, typer.Option("--check")] = False,
    source_commit_sha: Annotated[str | None, typer.Option()] = None,
    release_commit_sha: Annotated[str | None, typer.Option()] = None,
    built_at: Annotated[str | None, typer.Option()] = None,
    contract_root: Annotated[Path, typer.Option()] = support.DEFAULT_CONTRACT_ROOT,
    lock_path: Annotated[Path, typer.Option()] = support.DEFAULT_LOCK_PATH,
    mcp_path: Annotated[Path, typer.Option()] = support.DEFAULT_MCP_PATH,
    trusted_roots_path: Annotated[Path, typer.Option()] = support.DEFAULT_TRUSTED_ROOTS,
) -> None:
    """Generate frontend/public/build-info.json or check it without mutation."""
    resolved_root = root.resolve()
    try:
        paths = BuildPaths(
            root=resolved_root,
            output=_repo_cli_path(resolved_root, output, "output"),
            contract_root=_repo_cli_path(resolved_root, contract_root, "contract_root"),
            lock_path=_repo_cli_path(resolved_root, lock_path, "lock_path"),
            mcp_path=_repo_cli_path(resolved_root, mcp_path, "mcp_path"),
            trusted_roots_path=_repo_cli_path(
                resolved_root, trusted_roots_path, "trusted_roots_path"
            ),
        )
        generate(
            paths,
            check=check,
            source_sha=source_commit_sha,
            release_sha=release_commit_sha,
            built_at=built_at,
        )
    except BuildIdentityError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=3) from error
    typer.echo(
        "frontend-build-info-valid" if check else "frontend-build-info-generated"
    )


if __name__ == "__main__":
    typer.run(main)
