"""Canonical Twin API runtime-tree and service build identity."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Final

from telco_twin.domain.build_info import (
    EMPTY_CANONICAL_ARTIFACT_HASH,
    DigestScope,
    ServiceBuildInfo,
)
from telco_twin.domain.canonical import canonical_json_bytes
from telco_twin.safety.local_policy import LOCAL_POLICY_DEFINITION_HASH

if TYPE_CHECKING:
    from telco_twin.api.settings import ApiSettings
    from telco_twin.domain.approval import RootDescriptor

type SchemaHashes = dict[str, str]

SERVICE_NAME: Final = "telco-twin-api"
SERVICE_VERSION: Final = "0.1.0"


def repository_root() -> Path:
    """Resolve the repository root from the installed source layout."""
    return Path(__file__).resolve().parents[4]


def _runtime_files(root: Path) -> tuple[Path, ...]:
    candidates = [
        *sorted((root / "backend/src").rglob("*")),
        root / "backend/pyproject.toml",
        root / "backend/uv.lock",
        *sorted((root / "specs/schemas").rglob("*")),
    ]
    if any(path.is_symlink() for path in candidates):
        msg = "runtime identity path contains a symlink"
        raise RuntimeError(msg)
    files = tuple(
        path
        for path in candidates
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    )
    if any(not path.resolve().is_relative_to(root.resolve()) for path in files):
        msg = "runtime identity path escaped the repository"
        raise RuntimeError(msg)
    return tuple(sorted(files, key=lambda item: item.relative_to(root).as_posix()))


def runtime_tree_hash(root: Path | None = None) -> str:
    r"""Hash sorted `path\0sha256(file)\n` records over the exact API path set."""
    resolved_root = root or repository_root()
    records = b"".join(
        path.relative_to(resolved_root).as_posix().encode()
        + b"\0"
        + hashlib.sha256(path.read_bytes()).hexdigest().encode()
        + b"\n"
        for path in _runtime_files(resolved_root)
    )
    return hashlib.sha256(records).hexdigest()


def _schema_hashes(root: Path) -> SchemaHashes:
    return {
        path.name.removesuffix(".schema.json"): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((root / "specs/schemas").glob("*.json"))
    }


def build_service_info(settings: ApiSettings, root: RootDescriptor) -> ServiceBuildInfo:
    """Build the complete line-66 identity without self-referential generated artifacts."""
    repo = repository_root()
    tree_hash = runtime_tree_hash(repo)
    image_digest = settings.deployed_image_digest or f"sha256:{tree_hash}"
    scope = (
        DigestScope.REGISTRY_MANIFEST
        if settings.environment.value == "production"
        else DigestScope.LOCAL
    )
    trust_hash = hashlib.sha256(canonical_json_bytes([root.descriptor_hash])).hexdigest()
    return ServiceBuildInfo(
        service_name=SERVICE_NAME,
        version=SERVICE_VERSION,
        runtime_source_commit_sha=settings.runtime_source_commit_sha,
        release_commit_sha=settings.release_commit_sha,
        runtime_tree_hash=tree_hash,
        schema_hashes=_schema_hashes(repo),
        mcp_hash=EMPTY_CANONICAL_ARTIFACT_HASH,
        policy_hash=LOCAL_POLICY_DEFINITION_HASH,
        trusted_root_hashes=trust_hash,
        built_at=settings.built_at,
        image_digest=image_digest,
        digest_scope=scope,
        schema_version="1.0",
    )
