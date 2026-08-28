"""Task 9 build-identity and visual-manifest CLI contracts."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Final

from pydantic import JsonValue, TypeAdapter

REPO_ROOT: Final = Path(__file__).resolve().parents[3]
BUILD_SCRIPT: Final = REPO_ROOT / "scripts/generate_frontend_build_info.py"
JSON_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


def _json_object(raw: bytes) -> dict[str, JsonValue]:
    payload = JSON_ADAPTER.validate_json(raw)
    assert isinstance(payload, dict)
    return payload


def _run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)


def _copy_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    _ = shutil.copytree(
        REPO_ROOT,
        root,
        ignore=shutil.ignore_patterns(".git", ".venv", "node_modules", "dist", "__pycache__"),
    )
    _ = _run(["git", "init", "-q"], root)
    _ = _run(["git", "config", "user.email", "task9@example.invalid"], root)
    _ = _run(["git", "config", "user.name", "Task9"], root)
    assert _run(["git", "add", "."], root).returncode == 0
    assert _run(["git", "commit", "-qm", "fixture"], root).returncode == 0
    return root


def _generate(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _run(
        [sys.executable, str(BUILD_SCRIPT), "--root", str(root), *args],
        root,
    )


def test_build_info_generation_and_check_bind_clean_source(tmp_path: Path) -> None:
    # Given: a clean Git source tree with the declared frontend and schema inputs.
    root = _copy_repo(tmp_path)
    output = root / "frontend/public/build-info.json"
    # When: generation is followed by a checked-in artifact validation.
    generated = _generate(root)
    assert generated.returncode == 0, generated.stdout + generated.stderr
    output_hash = hashlib.sha256(output.read_bytes()).hexdigest()
    _ = _run(["git", "add", str(output.relative_to(root))], root)
    assert _run(["git", "commit", "-qm", "generated"], root).returncode == 0
    checked = _generate(root, "--check")
    # Then: UI identity is schema-shaped, canonical, and has no service image digest.
    assert checked.returncode == 0, checked.stdout + checked.stderr
    payload = _json_object(output.read_bytes())
    assert "image_digest" not in payload
    assert payload.get("asset_manifest_hash")
    assert payload.get("schema_hashes")
    extensions = payload.get("extensions")
    assert isinstance(extensions, dict)
    values = extensions.get("values")
    assert isinstance(values, dict)
    assert values.get("frontend_lock_hash")
    assert output_hash == hashlib.sha256(output.read_bytes()).hexdigest()


def test_build_info_generation_refuses_unrelated_dirty_source(tmp_path: Path) -> None:
    # Given: a source tree with a tracked edit unrelated to the generated output.
    root = _copy_repo(tmp_path)
    output = root / "frontend/public/build-info.json"
    output.unlink()
    _ = (root / "README.md").write_text("dirty\n", encoding="utf-8")
    # When: identity generation is attempted.
    result = _generate(root)
    # Then: the stable dirty-worktree error is nonzero and no artifact is written.
    assert result.returncode != 0
    assert "build-info-error:dirty-worktree:" in result.stderr
    assert not output.exists()


def test_build_info_check_refuses_forged_hash_without_mutating_file(tmp_path: Path) -> None:
    # Given: a checked-in generated artifact whose hash field is forged.
    root = _copy_repo(tmp_path)
    assert _generate(root).returncode == 0
    output = root / "frontend/public/build-info.json"
    _ = _run(["git", "add", str(output.relative_to(root))], root)
    assert _run(["git", "commit", "-qm", "generated"], root).returncode == 0
    before = output.read_bytes()
    payload = _json_object(before)
    payload["asset_manifest_hash"] = "0" * 64
    _ = output.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    # When: --check validates the forged checked-in file.
    result = _generate(root, "--check")
    # Then: validation fails closed and does not rewrite the forged bytes.
    assert result.returncode != 0
    assert "build-info-error:hash-mismatch:" in result.stderr
    forged = output.read_bytes()
    assert forged != before
    result = _generate(root, "--check")
    assert result.returncode != 0
    assert output.read_bytes() == forged


def test_build_info_check_detects_stale_schema_hash(tmp_path: Path) -> None:
    # Given: a clean generated identity committed against one schema tree.
    root = _copy_repo(tmp_path)
    assert _generate(root).returncode == 0
    output = root / "frontend/public/build-info.json"
    _ = _run(["git", "add", str(output.relative_to(root))], root)
    assert _run(["git", "commit", "-qm", "generated"], root).returncode == 0
    schema = root / "specs/schemas/event.schema.json"
    _ = schema.write_text(schema.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    # When: checked-in identity is checked after a schema-only change.
    result = _generate(root, "--check")
    # Then: the recorded contract hash no longer passes.
    assert result.returncode != 0
    assert "build-info-error:hash-mismatch:" in result.stderr


def test_build_info_check_rejects_ui_image_digest(tmp_path: Path) -> None:
    # Given: a checked-in UI artifact forged with the service-only digest field.
    root = _copy_repo(tmp_path)
    assert _generate(root).returncode == 0
    output = root / "frontend/public/build-info.json"
    _ = _run(["git", "add", str(output.relative_to(root))], root)
    assert _run(["git", "commit", "-qm", "generated"], root).returncode == 0
    payload = _json_object(output.read_bytes())
    payload["image_digest"] = "sha256:" + "0" * 64
    _ = output.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    # When: the UI identity checker reads the forged artifact.
    result = _generate(root, "--check")
    # Then: service identity cannot cross the UI schema boundary.
    assert result.returncode != 0
    assert "build-info-error:schema-mismatch:" in result.stderr
