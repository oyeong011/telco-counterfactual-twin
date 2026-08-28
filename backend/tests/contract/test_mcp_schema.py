"""MCP tool schema snapshot tests for the non-executing twin surface."""

import hashlib
import importlib.resources
import json
import os
from pathlib import Path

import pytest

from telco_twin.mcp.contracts import (
    MCP_PROTOCOL_VERSION,
    JsonMap,
    JsonSchema,
    JsonValue,
    _schema_json,
    tool_manifest,
    tool_manifest_hash,
)

from .mcp_vendor_verifier import require_artifact_paths, verify_vendor_artifacts

EXPECTED_TOOL_NAMES = (
    "list_scenarios",
    "get_scenario",
    "diagnose_scenario",
    "propose_patch",
    "simulate_patch",
    "compare_runs",
    "request_approval",
)


def test_tool_manifest_exposes_only_non_executing_tools() -> None:
    # Given: the twin MCP contract surface.
    manifest = tool_manifest()
    # When: clients inspect tool names and schemas.
    names = tuple(tool["name"] for tool in manifest["tools"])
    closed_inputs = tuple(
        tool["inputSchema"].get("additionalProperties") for tool in manifest["tools"]
    )
    # Then: clients receive only the exact evidence-recording tools with closed inputs.
    assert manifest["protocolVersion"] == MCP_PROTOCOL_VERSION
    assert names == EXPECTED_TOOL_NAMES
    assert closed_inputs == (False,) * len(EXPECTED_TOOL_NAMES)
    assert len(tool_manifest_hash()) == 64


def test_vendored_mcp_snapshot_records_pinned_wheel_authority() -> None:
    # Given: a vendored SDK snapshot used as implementation authority.
    snapshot_path = Path("docs/vendor/mcp-python-sdk-2.1.1.json")
    # When: the snapshot is loaded.
    snapshot = _json_map(snapshot_path)
    # Then: the wheel hash and supported transports are pinned.
    assert snapshot["package"] == "mcp"
    assert snapshot["version"] == "2.1.1"
    artifacts = _json_map(snapshot["artifacts"])
    runtime_wheel = _json_map(artifacts["runtime_wheel"])
    runtime_wheel_url = _json_str(runtime_wheel["url"])
    assert (
        runtime_wheel["sha256"]
        == "1c6c31c5d6471c58db76af3af8af67f46d11d01f0a59077d0a308cbdb3d3e915"
    )
    assert snapshot["protocol_version"] == "2025-06-18"
    assert snapshot["transports"] == ["stdio", "streamable-http"]
    assert runtime_wheel_url.endswith("mcp-2.1.1-py3-none-any.whl")
    runtime_members = _json_list(snapshot["runtime_member_files"])
    assert _json_map(runtime_members[2])["path"] == "mcp/server/stdio.py"
    assert "session_manager_handle_request" in _json_map(snapshot["signatures"])
    claimed_hash = _json_str(snapshot.pop("snapshot_sha256"))
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    assert claimed_hash == "deee4dd00ee6f2c6479cdd95e8def5c61716d8e8f1bbdebf4b6e64e694609057"
    assert hashlib.sha256(canonical).hexdigest() == claimed_hash


def test_vendored_mcp_snapshot_recomputes_installed_member_hashes() -> None:
    snapshot = _json_map(Path("docs/vendor/mcp-python-sdk-2.1.1.json"))
    mcp_root = importlib.resources.files("mcp")

    for member in _json_list(snapshot["runtime_member_files"]):
        spec = _json_map(member)
        relative = _json_str(spec["path"]).removeprefix("mcp/")
        digest = hashlib.sha256((mcp_root / relative).read_bytes()).hexdigest()
        assert digest == spec["sha256"]


def test_vendor_verifier_requires_explicit_local_artifacts() -> None:
    with pytest.raises(ValueError, match="explicit wheel and sdist paths are required"):
        _ = require_artifact_paths(None, Path("mcp-2.1.1.tar.gz"))


def test_vendor_verifier_recomputes_explicit_local_artifacts() -> None:
    wheel = os.environ.get("MCP_2_1_1_WHEEL")
    sdist = os.environ.get("MCP_2_1_1_SDIST")
    if wheel is None or sdist is None:
        pytest.skip("explicit MCP wheel and sdist paths are required for artifact proof")

    verification = verify_vendor_artifacts(
        Path("docs/vendor/mcp-python-sdk-2.1.1.json"),
        require_artifact_paths(Path(wheel), Path(sdist)),
    )

    assert verification.runtime_members == 7
    assert verification.supplemental_members == 7
    assert verification.signatures == 9
    assert verification.snapshot_sha256 == (
        "deee4dd00ee6f2c6479cdd95e8def5c61716d8e8f1bbdebf4b6e64e694609057"
    )


def test_vendor_verifier_rejects_mutated_signature_snapshot(tmp_path: Path) -> None:
    wheel = os.environ.get("MCP_2_1_1_WHEEL")
    sdist = os.environ.get("MCP_2_1_1_SDIST")
    if wheel is None or sdist is None:
        pytest.skip("explicit MCP wheel and sdist paths are required for mutation proof")
    snapshot = _json_map(Path("docs/vendor/mcp-python-sdk-2.1.1.json"))
    signatures = _json_map(snapshot["signatures"])
    signatures["server_run"] = "async def Server.run() -> None"
    snapshot["signatures"] = signatures
    del snapshot["snapshot_sha256"]
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    snapshot["snapshot_sha256"] = hashlib.sha256(canonical).hexdigest()
    mutated = tmp_path / "mutated-mcp-snapshot.json"
    _ = mutated.write_text(json.dumps(snapshot, sort_keys=True))

    with pytest.raises(ValueError, match="signature"):
        _ = verify_vendor_artifacts(
            mutated,
            require_artifact_paths(Path(wheel), Path(sdist)),
        )


def test_schema_json_preserves_optional_description_field() -> None:
    schema: JsonSchema = {"type": "object", "description": "described boundary"}

    assert _schema_json(schema)["description"] == "described boundary"


def _json_map(path: Path | JsonValue) -> JsonMap:
    value = json.loads(path.read_text()) if isinstance(path, Path) else path
    assert isinstance(value, dict)
    return value


def _json_list(value: JsonValue) -> list[JsonValue]:
    assert isinstance(value, list)
    return value


def _json_str(value: JsonValue) -> str:
    assert isinstance(value, str)
    return value
