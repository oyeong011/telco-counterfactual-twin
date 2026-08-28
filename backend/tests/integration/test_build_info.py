"""Liveness, readiness, and canonical build-identity HTTP tests."""

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from telco_twin.api.app import create_app
from telco_twin.api.build_identity import runtime_tree_hash
from telco_twin.api.contracts import ReadyResponse
from telco_twin.domain.build_info import ServiceBuildInfo

REPO_ROOT = Path(__file__).resolve().parents[3]


def _runtime_tree_hash() -> str:
    candidates = [
        *sorted((REPO_ROOT / "backend/src").rglob("*")),
        REPO_ROOT / "backend/pyproject.toml",
        REPO_ROOT / "backend/uv.lock",
        *sorted((REPO_ROOT / "specs/schemas").rglob("*")),
    ]
    files = tuple(
        path
        for path in candidates
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    )
    records = b"".join(
        (
            path.relative_to(REPO_ROOT).as_posix().encode()
            + b"\0"
            + hashlib.sha256(path.read_bytes()).hexdigest().encode()
            + b"\n"
        )
        for path in sorted(files, key=lambda item: item.relative_to(REPO_ROOT).as_posix())
    )
    return hashlib.sha256(records).hexdigest()


def test_liveness_readiness_and_local_build_identity_are_distinct_contracts() -> None:
    # Given: one normally configured local service.
    app = create_app()
    with TestClient(app) as client:
        # When: operations probes and identity are read.
        live = client.get("/healthz")
        ready = client.get("/readyz")
        build = client.get("/build-info")
    # Then: live/ready succeed and identity matches the exact runtime tree contract.
    assert live.status_code == 200
    assert live.json()["status"] == "live"
    assert ready.status_code == 200
    assert ReadyResponse.model_validate_json(ready.content).status == "ready"
    assert build.status_code == 200
    build_info = ServiceBuildInfo.model_validate_json(build.content)
    assert build_info.runtime_tree_hash == _runtime_tree_hash()
    assert build_info.digest_scope.value == "local"
    assert build_info.image_digest.startswith("sha256:")
    assert len(build_info.schema_hashes) == 12


def test_degraded_runtime_never_reports_misleading_readiness() -> None:
    # Given: a started process whose bounded state dependency is unavailable.
    app = create_app()
    app.runtime.set_available(False)
    with TestClient(app) as client:
        # When: both health probes are called.
        live = client.get("/healthz")
        ready = client.get("/readyz")
    # Then: process liveness remains truthful while readiness fails closed.
    assert live.status_code == 200
    assert ready.status_code == 503
    ready_body = ReadyResponse.model_validate_json(ready.content)
    assert ready_body.status == "degraded"
    assert ready_body.checks["state_store"] is False


def test_runtime_identity_rejects_symlinked_directory_in_component_scope(
    tmp_path: Path,
) -> None:
    # Given: a nominal component tree containing a directory symlink.
    source = tmp_path / "backend/src"
    schemas = tmp_path / "specs/schemas"
    outside = tmp_path / "outside"
    source.mkdir(parents=True)
    schemas.mkdir(parents=True)
    outside.mkdir()
    _ = (tmp_path / "backend/pyproject.toml").write_text("[project]\n")
    _ = (tmp_path / "backend/uv.lock").write_text("version = 1\n")
    _ = (source / "module.py").write_text("VALUE = 1\n")
    (source / "linked-directory").symlink_to(outside, target_is_directory=True)
    # When/Then: identity generation rejects the symlink before hashing files.
    with pytest.raises(RuntimeError):
        _ = runtime_tree_hash(tmp_path)
