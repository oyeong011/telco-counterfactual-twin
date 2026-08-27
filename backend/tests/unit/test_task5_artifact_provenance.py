"""Manual artifact commit/contract provenance regressions."""

import re
import subprocess
import sys
from pathlib import Path
from typing import Final

from pydantic import JsonValue, TypeAdapter

REPO_ROOT = Path(__file__).resolve().parents[3]
JSON_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)
SUCCESS_PATTERN: Final = re.compile(r"^task5-probe-pass artifact_hash=[0-9a-f]{64}\n$")


def _run_probe(output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "scripts.task5_safety_probe", "--out", str(output)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )


def test_probe_artifact_is_bound_to_reviewed_inputs_and_self_hash(tmp_path: Path) -> None:
    # Given: a fresh artifact from the real Task5 CLI.
    output = tmp_path / "task5-provenance.json"
    result = _run_probe(output)
    assert result.returncode == 0, result.stdout + result.stderr
    parsed = JSON_ADAPTER.validate_json(output.read_bytes())
    assert isinstance(parsed, dict)
    # When/Then: durable success names its exact code, command, seed, contracts, and inputs.
    provenance = parsed["provenance"]
    assert isinstance(provenance, dict)
    assert re.fullmatch(r"[0-9a-f]{40}", str(provenance["git_sha"]))
    assert provenance["invocation_id"] == "task5-safety-probe-v2"
    assert provenance["seed"] == 91
    assert isinstance(provenance["schema_hash"], str)
    assert isinstance(provenance["contract_hash"], str)
    assert isinstance(provenance["policy_hash"], str)
    assert isinstance(provenance["inputs"], dict)
    assert re.fullmatch(r"[0-9a-f]{64}", str(parsed["artifact_hash"]))


def test_probe_success_line_discloses_only_artifact_hash(tmp_path: Path) -> None:
    # Given: the real probe and an arbitrary local output path.
    output = tmp_path / "task5-success-line.json"
    # When: the CLI completes successfully.
    result = _run_probe(output)
    # Then: stdout exposes no path, token, key, or other mutable provenance.
    assert result.returncode == 0, result.stdout + result.stderr
    assert SUCCESS_PATTERN.fullmatch(result.stdout)
    assert str(output) not in result.stdout
