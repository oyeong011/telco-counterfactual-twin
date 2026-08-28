"""Task 9 build-identity and visual-manifest CLI contracts."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    import subprocess
    from pathlib import Path

from .task9_build_info_fixtures import (
    BUILD_SCRIPT,
    TRUST_DESCRIPTOR,
    canonical_json_file_hash,
    canonical_runtime_hash,
    copy_history_repo,
    copy_repo,
    emitted_asset_hash,
    json_object,
    run,
    write_stale_vite_dist,
)

PRE_POLICY_SHA = "ca791925169bfdf1959ee9e2d65213d7fdc97395"


def _generate(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run(
        [sys.executable, str(BUILD_SCRIPT), "--root", str(root), *args],
        root,
    )


def test_build_info_accepts_positional_output_for_checked_artifact(tmp_path: Path) -> None:
    # Given: a checked-in UI artifact at the canonical relative output path.
    root = copy_repo(tmp_path)
    assert not (root / "frontend/dist").exists()
    assert _generate(root).returncode == 0
    assert not (root / "frontend/dist").exists()
    output = root / "frontend/public/build-info.json"
    _ = run(["git", "add", str(output.relative_to(root))], root)
    assert run(["git", "commit", "-qm", "generated"], root).returncode == 0
    # When: the acceptance command passes the output positionally with --check.
    result = run(
        [
            sys.executable,
            str(BUILD_SCRIPT),
            "frontend/public/build-info.json",
            "--root",
            str(root),
            "--check",
        ],
        root,
    )
    # Then: the compatibility surface accepts the exact invocation.
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (root / "frontend/dist").exists()


@pytest.mark.parametrize("path_kind", ["absolute", "parent", "symlink"])
def test_build_info_rejects_repo_bound_path_escape(tmp_path: Path, path_kind: str) -> None:
    # Given: one path that bypasses a repository-relative input boundary.
    root = copy_repo(tmp_path)
    external = tmp_path / "external-lock.yaml"
    _ = external.write_text("lockfileVersion: 9\n", encoding="utf-8")
    linked = root / "frontend/linked-lock.yaml"
    if path_kind == "symlink":
        linked.symlink_to(root / "frontend/pnpm-lock.yaml")
    values = {
        "absolute": str(root / "frontend/pnpm-lock.yaml"),
        "parent": "../external-lock.yaml",
        "symlink": "frontend/linked-lock.yaml",
    }
    # When: generation is told to hash the hostile lock path.
    result = _generate(root, "--lock-path", values[path_kind])
    # Then: absolute, escaping, and symlink inputs all fail closed.
    assert result.returncode != 0
    assert "build-info-error:path-traversal:" in result.stderr


def test_build_info_binds_override_to_declared_commit_tree(tmp_path: Path) -> None:
    # Given: a base source commit and a later commit changing a UI runtime file.
    root = copy_repo(tmp_path)
    base = run(["git", "rev-parse", "HEAD"], root).stdout.strip()
    source = root / "frontend/src/main.tsx"
    _ = source.write_text(source.read_text(encoding="utf-8") + "\n// changed\n", encoding="utf-8")
    assert run(["git", "add", str(source.relative_to(root))], root).returncode == 0
    assert run(["git", "commit", "-qm", "ui change"], root).returncode == 0
    # When: generation for the new tree overrides source identity to the old commit.
    result = _generate(root, "--source-commit-sha", base)
    # Then: the declared commit's exact runtime tree must match the current source.
    assert result.returncode != 0
    assert "build-info-error:source-commit-mismatch:" in result.stderr


def test_build_info_binds_release_override_to_declared_commit_tree(tmp_path: Path) -> None:
    # Given: a base commit followed by a committed UI runtime change.
    root = copy_repo(tmp_path)
    base = run(["git", "rev-parse", "HEAD"], root).stdout.strip()
    source = root / "frontend/src/main.tsx"
    _ = source.write_text(
        source.read_text(encoding="utf-8") + "\n// release drift\n", encoding="utf-8"
    )
    assert run(["git", "add", str(source.relative_to(root))], root).returncode == 0
    assert run(["git", "commit", "-qm", "release ui change"], root).returncode == 0
    # When: release identity is overridden to the stale base tree.
    result = _generate(root, "--release-commit-sha", base)
    # Then: release SHA cannot merely be an arbitrary ancestor.
    assert result.returncode != 0
    assert "build-info-error:release-commit-mismatch:" in result.stderr


def test_build_info_rejects_pre_policy_source_and_release_commit(tmp_path: Path) -> None:
    # Given: real history whose older commit predates the pnpm esbuild allowlist.
    root = copy_history_repo(tmp_path)
    installed = run(["pnpm", "--dir", "frontend", "install", "--frozen-lockfile"], root)
    assert installed.returncode == 0, installed.stdout + installed.stderr
    # When: both identity fields are forged to the otherwise content-compatible commit.
    result = _generate(
        root,
        "--source-commit-sha",
        PRE_POLICY_SHA,
        "--release-commit-sha",
        PRE_POLICY_SHA,
    )
    # Then: the canonical runtime tree rejects the pre-policy commit.
    assert result.returncode != 0
    assert "build-info-error:source-commit-mismatch:" in result.stderr


def test_build_info_generation_and_check_bind_clean_source(tmp_path: Path) -> None:
    # Given: a clean Git source tree with the declared frontend and schema inputs.
    root = copy_repo(tmp_path)
    output = root / "frontend/public/build-info.json"
    # When: generation is followed by a checked-in artifact validation.
    generated = _generate(root)
    assert generated.returncode == 0, generated.stdout + generated.stderr
    before_check = output.read_bytes()
    _ = run(["git", "add", str(output.relative_to(root))], root)
    assert run(["git", "commit", "-qm", "generated"], root).returncode == 0
    checked = _generate(root, "--check")
    # Then: UI identity is schema-shaped, canonical, and has no service image digest.
    assert checked.returncode == 0, checked.stdout + checked.stderr
    payload = json_object(output.read_bytes())
    assert "image_digest" not in payload
    assert payload.get("runtime_tree_hash") == canonical_runtime_hash(root)
    assert not (root / "frontend/dist").exists()
    assert payload.get("trusted_root_hashes") == canonical_json_file_hash(root / TRUST_DESCRIPTOR)
    assert payload.get("schema_hashes")
    extensions = payload.get("extensions")
    assert isinstance(extensions, dict)
    values = extensions.get("values")
    assert isinstance(values, dict)
    assert values.get("frontend_lock_hash")
    assert output.read_bytes() == before_check


def test_build_info_generation_refuses_unrelated_dirty_source(tmp_path: Path) -> None:
    # Given: a source tree with a tracked edit unrelated to the generated output.
    root = copy_repo(tmp_path)
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
    root = copy_repo(tmp_path)
    assert _generate(root).returncode == 0
    output = root / "frontend/public/build-info.json"
    _ = run(["git", "add", str(output.relative_to(root))], root)
    assert run(["git", "commit", "-qm", "generated"], root).returncode == 0
    before = output.read_bytes()
    payload = json_object(before)
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
    root = copy_repo(tmp_path)
    assert _generate(root).returncode == 0
    output = root / "frontend/public/build-info.json"
    _ = run(["git", "add", str(output.relative_to(root))], root)
    assert run(["git", "commit", "-qm", "generated"], root).returncode == 0
    schema = root / "specs/schemas/event.schema.json"
    _ = schema.write_text(schema.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    # When: checked-in identity is checked after a schema-only change.
    result = _generate(root, "--check")
    # Then: the declared source commit no longer matches the canonical runtime tree.
    assert result.returncode != 0
    assert "build-info-error:source-commit-mismatch:" in result.stderr


def test_build_info_check_rejects_ui_image_digest(tmp_path: Path) -> None:
    # Given: a checked-in UI artifact forged with the service-only digest field.
    root = copy_repo(tmp_path)
    assert _generate(root).returncode == 0
    output = root / "frontend/public/build-info.json"
    _ = run(["git", "add", str(output.relative_to(root))], root)
    assert run(["git", "commit", "-qm", "generated"], root).returncode == 0
    payload = json_object(output.read_bytes())
    payload["image_digest"] = "sha256:" + "0" * 64
    _ = output.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    # When: the UI identity checker reads the forged artifact.
    result = _generate(root, "--check")
    # Then: service identity cannot cross the UI schema boundary.
    assert result.returncode != 0
    assert "build-info-error:schema-mismatch:" in result.stderr


def test_build_info_does_not_trust_stale_ignored_dist(tmp_path: Path) -> None:
    # Given: a forged ignored output tree unrelated to the committed UI source.
    root = copy_repo(tmp_path)
    _ = write_stale_vite_dist(root)
    stale_hash = emitted_asset_hash(root)
    assert _generate(root).returncode == 0
    output = root / "frontend/public/build-info.json"
    payload = json_object(output.read_bytes())
    _ = run(["git", "add", str(output.relative_to(root))], root)
    assert run(["git", "commit", "-qm", "generated"], root).returncode == 0
    # When: the checked artifact is verified while stale dist remains present.
    result = _generate(root, "--check")
    # Then: the forged ignored files neither define nor invalidate source identity.
    assert result.returncode == 0, result.stdout + result.stderr
    assert payload.get("asset_manifest_hash") != stale_hash


def test_build_info_vite_failure_preserves_existing_output_atomically(tmp_path: Path) -> None:
    # Given: an existing output but no installed Vite executable.
    root = copy_repo(tmp_path)
    output = root / "frontend/public/build-info.json"
    before = output.read_bytes()
    (root / "frontend/node_modules").unlink()
    # When: generation fails before publication.
    result = _generate(root)
    # Then: the previous artifact remains byte-identical.
    assert result.returncode != 0
    assert "build-info-error:vite-unavailable:" in result.stderr
    assert output.read_bytes() == before


def test_standard_frontend_build_copies_identity_and_emits_manifest(tmp_path: Path) -> None:
    # Given: a generated public identity from an ephemeral source build.
    root = copy_repo(tmp_path)
    (root / "frontend/node_modules").unlink()
    installed = run(["pnpm", "--dir", "frontend", "install", "--frozen-lockfile"], root)
    assert installed.returncode == 0, installed.stdout + installed.stderr
    assert "Ignored build scripts" not in installed.stdout + installed.stderr
    assert _generate(root).returncode == 0
    public = root / "frontend/public/build-info.json"
    # When: the standard frontend build script runs afterward.
    result = run(["pnpm", "--dir", "frontend", "build"], root)
    # Then: production output carries byte-identical identity and a Vite manifest.
    assert result.returncode == 0, result.stdout + result.stderr
    assert (root / "frontend/dist/build-info.json").read_bytes() == public.read_bytes()
    assert (root / "frontend/dist/.vite/manifest.json").is_file()
    payload = json_object(public.read_bytes())
    assert payload.get("asset_manifest_hash") == emitted_asset_hash(root)


def test_build_info_ignores_files_outside_canonical_runtime_contract(tmp_path: Path) -> None:
    # Given: two commits differing only in a file excluded by the plan's UI path set.
    root = copy_repo(tmp_path)
    before = canonical_runtime_hash(root)
    index = root / "frontend/index.html"
    _ = index.write_text(index.read_text(encoding="utf-8") + "\n<!-- shell -->\n", encoding="utf-8")
    assert run(["git", "add", str(index.relative_to(root))], root).returncode == 0
    assert run(["git", "commit", "-qm", "shell only"], root).returncode == 0
    # When: identity is generated from the later commit.
    result = _generate(root)
    # Then: runtime hash remains exactly the plan's canonical component set.
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json_object((root / "frontend/public/build-info.json").read_bytes())
    assert payload.get("runtime_tree_hash") == before
