"""Canonical service and UI build-identity contracts."""

from __future__ import annotations

from enum import StrEnum, unique
from typing import Annotated, Final

from pydantic import Field

from ._contract import (
    ContractId,
    GitCommitSha,
    RootContract,
    SafeKey,
    SemanticVersion,
    Sha256Hex,
    UtcTimestamp,
)

EMPTY_CANONICAL_ARTIFACT_HASH: Final = (
    "ca3d163bab055381827226140568f3bef7eaac187cebd76878e0b63e9e442356"
)


@unique
class DigestScope(StrEnum):
    """Where the injected service image digest was resolved."""

    LOCAL = "local"
    REGISTRY_MANIFEST = "registry_manifest"


class BuildInfo(RootContract):
    """Fields required by every one of the five public component identities."""

    service_name: ContractId
    version: SemanticVersion
    runtime_source_commit_sha: GitCommitSha
    release_commit_sha: GitCommitSha
    runtime_tree_hash: Sha256Hex
    schema_hashes: Annotated[dict[SafeKey, Sha256Hex], Field(min_length=1, max_length=64)]
    mcp_hash: Sha256Hex
    policy_hash: Sha256Hex
    trusted_root_hashes: Annotated[tuple[Sha256Hex, ...], Field(max_length=16)]
    built_at: UtcTimestamp


class ServiceBuildInfo(BuildInfo):
    """Runtime service identity with an externally injected OCI digest."""

    image_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    digest_scope: DigestScope


class UiBuildInfo(BuildInfo):
    """Static UI identity bound to its emitted-asset manifest."""

    asset_manifest_hash: Sha256Hex
