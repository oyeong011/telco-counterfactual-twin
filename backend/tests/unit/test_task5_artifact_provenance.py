"""Manual artifact commit/contract provenance regressions."""

import hashlib
import re
import subprocess
from pathlib import Path
from typing import Final

import pytest
from pydantic import JsonValue, TypeAdapter

from .probe_git_support import (
    checkout_head,
    clean_probe_checkout,
    run_local_validation,
    run_probe,
)

JSON_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)
SUCCESS_PATTERN: Final = re.compile(r"^task5-probe-pass artifact_hash=[0-9a-f]{64}\n$")


def test_probe_artifact_is_bound_to_reviewed_inputs_and_self_hash(tmp_path: Path) -> None:
    # Given: a fresh artifact from the real Task5 CLI.
    checkout = clean_probe_checkout(tmp_path)
    output = tmp_path / "task5-provenance.json"
    result = run_probe(checkout, output)
    assert result.returncode == 0, result.stdout + result.stderr
    parsed = JSON_ADAPTER.validate_json(output.read_bytes())
    assert isinstance(parsed, dict)
    # When/Then: durable success names its exact code, command, seed, contracts, and inputs.
    provenance = parsed["provenance"]
    assert isinstance(provenance, dict)
    assert re.fullmatch(r"[0-9a-f]{40}", str(provenance["git_sha"]))
    assert provenance["git_sha"] == checkout_head(checkout)
    assert provenance["invocation_id"] == "task5-safety-probe-v2"
    assert provenance["seed"] == 91
    assert provenance["worktree_clean"] is True
    assert provenance["status_hash"] == hashlib.sha256(b"").hexdigest()
    assert isinstance(provenance["schema_hash"], str)
    assert isinstance(provenance["contract_hash"], str)
    assert isinstance(provenance["policy_hash"], str)
    assert isinstance(provenance["inputs"], dict)
    assert re.fullmatch(r"[0-9a-f]{64}", str(parsed["artifact_hash"]))


def test_probe_success_line_discloses_only_artifact_hash(tmp_path: Path) -> None:
    # Given: the real probe and an arbitrary local output path.
    checkout = clean_probe_checkout(tmp_path)
    output = tmp_path / "task5-success-line.json"
    # When: the CLI completes successfully.
    result = run_probe(checkout, output)
    # Then: stdout exposes no path, token, key, or other mutable provenance.
    assert result.returncode == 0, result.stdout + result.stderr
    assert SUCCESS_PATTERN.fullmatch(result.stdout)
    assert str(output) not in result.stdout


@pytest.mark.parametrize("dirty_kind", ["tracked", "staged", "untracked"])
def test_probe_refuses_dirty_repository_without_writing_pass_artifact(
    tmp_path: Path,
    dirty_kind: str,
) -> None:
    checkout = clean_probe_checkout(tmp_path)
    tracked = checkout / "README.md"
    if dirty_kind in {"tracked", "staged"}:
        _ = tracked.write_text(
            tracked.read_text(encoding="utf-8") + "\ndirty fixture\n",
            encoding="utf-8",
        )
    else:
        _ = (checkout / "untracked-dirty.txt").write_text("dirty\n", encoding="utf-8")
    if dirty_kind == "staged":
        _ = subprocess.run(
            ["git", "add", "README.md"],
            cwd=checkout,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    output = tmp_path / f"dirty-{dirty_kind}.json"
    result = run_probe(checkout, output)
    assert result.returncode == 1
    assert "artifact-worktree-dirty" in result.stderr
    assert not output.exists()


def test_local_artifact_validator_rechecks_live_head_and_clean_status(
    tmp_path: Path,
) -> None:
    checkout = clean_probe_checkout(tmp_path)
    output = tmp_path / "locally-validated.json"
    generated = run_probe(checkout, output)
    assert generated.returncode == 0, generated.stdout + generated.stderr
    clean = run_local_validation(checkout, output)
    assert clean.returncode == 0, clean.stdout + clean.stderr
    _ = (checkout / "dirty-after-artifact.txt").write_text("dirty\n", encoding="utf-8")
    dirty = run_local_validation(checkout, output)
    assert dirty.returncode == 1
    assert "artifact-worktree-dirty" in dirty.stderr


def test_probe_requires_output_path_outside_target_repository(tmp_path: Path) -> None:
    checkout = clean_probe_checkout(tmp_path)
    output = checkout / "probe-output.json"
    result = run_probe(checkout, output)
    assert result.returncode == 1
    assert "artifact-output-inside-repository" in result.stderr
    assert not output.exists()
