from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT: Final = Path(__file__).resolve().parents[2]


@pytest.fixture
def clean_git_repo(tmp_path: Path) -> Path:
    """Create a committed repository for worktree-integrity CLI tests."""
    _ = subprocess.run(
        ["git", "init", "-b", "main", str(tmp_path)], check=True, capture_output=True
    )
    _ = subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "Todo One Test"],
        check=True,
        capture_output=True,
    )
    _ = subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "todo-one@example.invalid"],
        check=True,
        capture_output=True,
    )
    _ = (tmp_path / "README.md").write_text("# fixture\n", encoding="utf-8")
    _ = subprocess.run(["git", "-C", str(tmp_path), "add", "README.md"], check=True)
    _ = subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-m", "fixture"],
        check=True,
        capture_output=True,
    )
    return tmp_path


def run_project_script(
    script_name: str,
    *arguments: str,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a repository script with the active uv-managed Python 3.12 interpreter."""
    script_path = REPO_ROOT / "scripts" / script_name
    assert script_path.is_file(), f"missing implementation: {script_path}"
    command_environment = os.environ.copy()
    if environment is not None:
        command_environment.update(environment)
    return subprocess.run(
        [sys.executable, str(script_path), *arguments],
        cwd=REPO_ROOT,
        env=command_environment,
        check=False,
        capture_output=True,
        text=True,
    )
