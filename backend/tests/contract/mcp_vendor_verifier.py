"""Deterministic verifier for pinned MCP 2.1.1 vendor artifacts."""

from __future__ import annotations

import hashlib
import json
import sys
import tarfile
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter, ValidationError

from telco_twin.mcp.contracts import JsonMap, JsonValue

from .mcp_vendor_signatures import (
    SIGNATURE_TARGETS,
    derive_sdist_signatures,
    derive_wheel_signatures,
    normalize_signature,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

JSON_MAP_ADAPTER: TypeAdapter[JsonMap] = TypeAdapter(dict[str, JsonValue])
EXPECTED_SIGNATURES: Final = frozenset(SIGNATURE_TARGETS)
ARGUMENT_COUNT: Final = 3


@dataclass(frozen=True, slots=True)
class VendorArtifactPaths:
    """Explicit local artifact paths required for network-independent proof."""

    wheel: Path
    sdist: Path


@dataclass(frozen=True, slots=True)
class VendorVerification:
    """Counts and artifact digests proven from local bytes."""

    wheel_sha256: str
    sdist_sha256: str
    runtime_members: int
    supplemental_members: int
    signatures: int
    snapshot_sha256: str


def require_artifact_paths(wheel: Path | None, sdist: Path | None) -> VendorArtifactPaths:
    """Return local artifact paths or fail before claiming artifact verification."""
    if wheel is None or sdist is None:
        message = "explicit wheel and sdist paths are required"
        raise ValueError(message)
    return VendorArtifactPaths(wheel=wheel, sdist=sdist)


def verify_vendor_artifacts(
    snapshot_path: Path,
    artifacts: VendorArtifactPaths,
) -> VendorVerification:
    """Recompute the pinned snapshot from exact local wheel and sdist bytes."""
    snapshot = _read_snapshot(snapshot_path)
    artifact_map = _map(snapshot["artifacts"])
    wheel = _map(artifact_map["runtime_wheel"])
    sdist = _map(artifact_map["source_distribution"])
    wheel_sha = _verify_artifact_file(artifacts.wheel, wheel)
    sdist_sha = _verify_artifact_file(artifacts.sdist, sdist)
    runtime_count = _verify_zip_members(artifacts.wheel, _list(snapshot["runtime_member_files"]))
    supplemental_count = _verify_tar_members(
        artifacts.sdist, _list(snapshot["supplemental_sdist_files"])
    )
    signature_count = _verify_signatures(
        _map(snapshot["signatures"]), artifacts.wheel, artifacts.sdist
    )
    snapshot_sha = _verify_snapshot_hash(snapshot)
    return VendorVerification(
        wheel_sha256=wheel_sha,
        sdist_sha256=sdist_sha,
        runtime_members=runtime_count,
        supplemental_members=supplemental_count,
        signatures=signature_count,
        snapshot_sha256=snapshot_sha,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for manual vendor artifact verification."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != ARGUMENT_COUNT:
        message = "usage: vendor_verifier SNAPSHOT_JSON MCP_WHEEL MCP_SDIST"
        raise SystemExit(message)
    verification = verify_vendor_artifacts(
        Path(args[0]),
        require_artifact_paths(Path(args[1]), Path(args[2])),
    )
    _ = sys.stdout.write(json.dumps(asdict(verification), sort_keys=True))
    _ = sys.stdout.write("\n")
    return 0


def _read_snapshot(path: Path) -> JsonMap:
    try:
        return JSON_MAP_ADAPTER.validate_json(path.read_bytes())
    except (OSError, ValidationError) as exc:
        message = f"invalid vendor snapshot: {path}"
        raise ValueError(message) from exc


def _verify_artifact_file(path: Path, artifact: JsonMap) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if path.name != _str(artifact["filename"]) or digest != _str(artifact["sha256"]):
        message = f"artifact identity mismatch: {path}"
        raise ValueError(message)
    if path.stat().st_size != _int(artifact["size"]):
        message = f"artifact size mismatch: {path}"
        raise ValueError(message)
    return digest


def _verify_zip_members(path: Path, members: list[JsonValue]) -> int:
    with zipfile.ZipFile(path) as archive:
        for member in members:
            spec = _map(member)
            actual = hashlib.sha256(archive.read(_str(spec["path"]))).hexdigest()
            if actual != _str(spec["sha256"]):
                message = f"wheel member hash mismatch: {spec['path']}"
                raise ValueError(message)
    return len(members)


def _verify_tar_members(path: Path, members: list[JsonValue]) -> int:
    with tarfile.open(path, "r:gz") as archive:
        for member in members:
            spec = _map(member)
            extracted = archive.extractfile(f"mcp-2.1.1/{_str(spec['path'])}")
            if extracted is None:
                message = f"sdist member missing: {spec['path']}"
                raise ValueError(message)
            actual = hashlib.sha256(extracted.read()).hexdigest()
            if actual != _str(spec["sha256"]):
                message = f"sdist member hash mismatch: {spec['path']}"
                raise ValueError(message)
    return len(members)


def _verify_signatures(signatures: JsonMap, wheel_path: Path, sdist_path: Path) -> int:
    if frozenset(signatures) != EXPECTED_SIGNATURES:
        message = "signature set mismatch"
        raise ValueError(message)
    wheel_signatures = derive_wheel_signatures(wheel_path)
    sdist_signatures = derive_sdist_signatures(sdist_path)
    if wheel_signatures != sdist_signatures:
        message = "wheel/sdist signature mismatch"
        raise ValueError(message)
    for key, signature in signatures.items():
        if normalize_signature(_str(signature)) != wheel_signatures[key]:
            message = f"signature mismatch: {key}"
            raise ValueError(message)
    return len(signatures)


def _verify_snapshot_hash(snapshot: JsonMap) -> str:
    claimed = _str(snapshot["snapshot_sha256"])
    canonical_source = dict(snapshot)
    del canonical_source["snapshot_sha256"]
    canonical = json.dumps(canonical_source, sort_keys=True, separators=(",", ":")).encode()
    actual = hashlib.sha256(canonical).hexdigest()
    if actual != claimed:
        message = "snapshot hash mismatch"
        raise ValueError(message)
    return actual


def _map(value: JsonValue) -> JsonMap:
    if not isinstance(value, dict):
        message = "expected JSON object"
        raise TypeError(message)
    return value


def _list(value: JsonValue) -> list[JsonValue]:
    if not isinstance(value, list):
        message = "expected JSON array"
        raise TypeError(message)
    return value


def _str(value: JsonValue) -> str:
    if not isinstance(value, str):
        message = "expected JSON string"
        raise TypeError(message)
    return value


def _int(value: JsonValue) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        message = "expected JSON integer"
        raise TypeError(message)
    return value


if __name__ == "__main__":
    raise SystemExit(main())
