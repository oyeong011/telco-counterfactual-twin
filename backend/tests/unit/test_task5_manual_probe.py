"""Real CLI Task5 evidence-flow probe test."""

import subprocess
import sys
from pathlib import Path

from telco_twin.state.probe_evidence import ProbeArtifact

REPO_ROOT = Path(__file__).resolve().parents[3]


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
    artifact = ProbeArtifact.model_validate_json(output.read_text(encoding="utf-8"))
    git_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    ).stdout.strip()
    assert artifact.provenance.git_sha == git_sha
    assert artifact.result == "pass"
    assert artifact.positive.baseline_hash_before == artifact.positive.baseline_hash_after
    assert artifact.positive.approval_state == "approved"
    assert artifact.negative.replay_code == "nonce-replayed"
    assert artifact.negative.epoch_code == "demo_session_lost"
    assert artifact.negative.malformed_code == "demo_token_invalid"
    assert artifact.negative.unsafe_patch_code == "patch-parameter-range"
    assert artifact.negative.stale_policy_code == "observation-stale"
    assert artifact.negative.unsimulated_policy_code == (
        "patch-hash-missing,simulation-hash-missing,simulation-missing"
    )
    assert artifact.negative.forged_proof_code == "approval-signature-invalid"
    assert artifact.negative.dirty_baseline_code == "manifest-integrity"
    assert artifact.negative.expired_proof_code == "approval-expired"
    assert artifact.negative.cross_session_code == "certificate-binding-mismatch"
    assert result.stdout == f"task5-probe-pass artifact_hash={artifact.artifact_hash}\n"
    assert "APPROVAL_ROOT_KEY_SECRET" not in output.read_text(encoding="utf-8")
