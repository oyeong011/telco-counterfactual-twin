"""Real CLI Task5 evidence-flow probe test."""

import subprocess
import sys
from pathlib import Path
from typing import Final

from pydantic import JsonValue, TypeAdapter

REPO_ROOT = Path(__file__).resolve().parents[3]
JSON_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


def test_probe_runs_complete_evidence_flow_and_negative_paths(tmp_path: Path) -> None:
    # Given: a fresh output path and the real project runtime.
    output = tmp_path / "task5-probe.json"
    # When: the CLI drives scenario through evidence-only approval and adversarial paths.
    result = subprocess.run(
        [sys.executable, "-m", "scripts.task5_safety_probe", "--out", str(output)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    # Then: the artifact proves immutable baseline, offline chain, and stable failures.
    assert result.returncode == 0, result.stdout + result.stderr
    parsed = JSON_ADAPTER.validate_json(output.read_bytes())
    assert isinstance(parsed, dict)
    assert parsed["result"] == "pass"
    positive = parsed["positive"]
    assert isinstance(positive, dict)
    assert positive["baseline_hash_before"] == positive["baseline_hash_after"]
    assert positive["approval_state"] == "approved"
    negative = parsed["negative"]
    assert isinstance(negative, dict)
    assert negative["replay_code"] == "nonce-replayed"
    assert negative["epoch_code"] == "demo_session_lost"
    assert negative["unsafe_patch_code"] == "patch-parameter-range"
    assert "APPROVAL_ROOT_KEY_SECRET" not in output.read_text(encoding="utf-8")
