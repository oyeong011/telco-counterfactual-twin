"""Full-checkout regeneration and canonical artifact boundary tests."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from telco_twin.eval.artifacts import load_bundle, write_bundle

REPO_ROOT = Path(__file__).parents[3]
EXPECTED_FILES = frozenset(
    {
        "counterfactual.json",
        "diagnosis-summary.json",
        "diagnosis.jsonl",
        "replay-hashes.json",
        "safety-gate.json",
    }
)


def _run(repo: Path, arguments: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(repo / "backend/src"), str(repo)))
    return subprocess.run(
        (sys.executable, *arguments),
        cwd=repo,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _full_checkout(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    _ = shutil.copytree(
        REPO_ROOT,
        repo,
        ignore=shutil.ignore_patterns(
            ".git",
            ".venv",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
        ),
    )
    commands = (
        ("git", "init", "-q"),
        ("git", "config", "user.name", "Regeneration Test"),
        ("git", "config", "user.email", "regeneration@example.invalid"),
        ("git", "add", "-A"),
        ("git", "commit", "-qm", "source fixture"),
    )
    for command in commands:
        _ = subprocess.run(command, cwd=repo, check=True)
    return repo


def _generate(
    repo: Path,
    output: str = "artifacts/eval",
) -> subprocess.CompletedProcess[str]:
    return _run(
        repo,
        (
            "scripts/run_benchmark.py",
            "--split",
            "heldout",
            "--safety-set",
            "backend/fixtures/eval/safety-v1.jsonl",
            "--seed",
            "20270827",
            "--out",
            output,
        ),
    )


def test_full_checkout_documented_regeneration_is_atomic_and_deterministic(
    tmp_path: Path,
) -> None:
    # Given: a normal full checkout with the prior five tracked artifacts present.
    repo = _full_checkout(tmp_path)
    output = repo / "artifacts/eval"
    _ = subprocess.run(("/bin/rm", "-rf", str(output)), check=True)
    # When: the documented canonical benchmark and acceptance commands run.
    first = _generate(repo)
    assert first.returncode == 0, first.stdout + first.stderr
    accepted = _run(repo, ("scripts/assert_acceptance.py", "artifacts/eval"))
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    first_bytes = {path.name: path.read_bytes() for path in output.iterdir()}
    # Then: exact five files exist and an identical second invocation is byte-stable.
    assert frozenset(first_bytes) == EXPECTED_FILES
    _ = subprocess.run(("/bin/rm", "-rf", str(output)), check=True)
    second = _generate(repo)
    assert second.returncode == 0, second.stdout + second.stderr
    assert first_bytes == {path.name: path.read_bytes() for path in output.iterdir()}


def test_clean_full_checkout_rejects_arbitrary_output(tmp_path: Path) -> None:
    # Given: a completely clean normal checkout and a noncanonical output directory.
    repo = _full_checkout(tmp_path)
    # When: benchmark generation requests an arbitrary path with no dirty-state signal.
    result = _generate(repo, "elsewhere/eval")
    # Then: canonical output validation fails before the empty-status fast path.
    assert result.returncode == 2, result.stdout + result.stderr
    assert not (repo / "elsewhere/eval").exists()


def test_interrupted_bundle_write_leaves_no_partial_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a real parsed bundle and an interruption during the third staged write.
    bundle = load_bundle(REPO_ROOT / "artifacts/eval")
    original = Path.write_text
    calls = 0

    def interrupted(path: Path, data: str, *, encoding: str | None = None) -> int:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise KeyboardInterrupt
        return original(path, data, encoding=encoding)

    monkeypatch.setattr(Path, "write_text", interrupted)
    output = tmp_path / "eval"
    # When: publication is interrupted before the atomic directory replacement.
    with pytest.raises(KeyboardInterrupt):
        write_bundle(bundle, output)
    # Then: neither the final output nor private staging directory survives.
    assert not output.exists()
    assert tuple(tmp_path.glob(".eval.*")) == ()


@pytest.mark.parametrize(
    "variant",
    ["staged", "untracked", "nested", "unrelated", "rename", "arbitrary-output"],
)
def test_full_checkout_rejects_noncanonical_regeneration_state(
    tmp_path: Path,
    variant: str,
) -> None:
    # Given: a full checkout with one forbidden status/output transition.
    repo = _full_checkout(tmp_path)
    output = repo / "artifacts/eval"
    if variant == "rename":
        _ = subprocess.run(
            ("git", "mv", "artifacts/eval/counterfactual.json", "artifacts/eval/renamed.json"),
            cwd=repo,
            check=True,
        )
    else:
        _ = subprocess.run(("/bin/rm", "-rf", str(output)), check=True)
        if variant in {"untracked", "nested"}:
            target = output / ("extra.json" if variant == "untracked" else "nested/x.json")
            target.parent.mkdir(parents=True, exist_ok=True)
            _ = target.write_text("{}\n", encoding="utf-8")
        elif variant == "staged":
            _ = subprocess.run(("git", "add", "-u", "artifacts/eval"), cwd=repo, check=True)
        elif variant == "unrelated":
            _ = (repo / "README.md").write_text("unrelated\n", encoding="utf-8")
    requested_output = "elsewhere/eval" if variant == "arbitrary-output" else "artifacts/eval"
    # When: benchmark generation evaluates the repository state.
    result = _generate(repo, requested_output)
    # Then: every staged/extra/nested/unrelated/rename/arbitrary-output case fails closed.
    assert result.returncode == 2, result.stdout + result.stderr
    assert not (repo / "elsewhere/eval").exists()
