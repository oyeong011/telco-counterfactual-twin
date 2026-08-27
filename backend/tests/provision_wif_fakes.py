"""Reusable fake CLI boundaries for provision-WIF integration tests."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

FAKE_HEAD_SHA = "c" * 40


def write_deny_workflow_tools(tool_dir: Path) -> None:
    """Create fake git/gh commands for an expected deny-exchange result."""
    git = tool_dir / "git"
    gh = tool_dir / "gh"
    _ = git.write_text(
        f"#!/bin/sh\nprintf '%s\\n' '{FAKE_HEAD_SHA}'\n",
        encoding="utf-8",
    )
    _ = gh.write_text(
        f"""#!/bin/sh
case "$*" in
  "api users/oyeong011"*) printf '%s\\n' '12345678' ;;
  "run list"*) printf '%s\\n' '[]' ;;
  "workflow run"*) printf '%s\\n' 'https://example.invalid/actions/runs/123' ;;
  "run watch"*) if test "${{FAKE_DENY_ACCEPTED:-0}}" = 1; then exit 1; fi ;;
  *"--json headSha,status,conclusion,url"*)
    if test "${{FAKE_DENY_ACCEPTED:-0}}" = 1; then
      conclusion=failure
    else
      conclusion=success
    fi
    metadata='{{"headSha":"{FAKE_HEAD_SHA}","status":"completed","conclusion":"%s","url":"x"}}'
    printf "$metadata\\n" "$conclusion"
    ;;
  *"--json headSha,conclusion,url"*)
    if test "${{FAKE_DENY_ACCEPTED:-0}}" = 1; then
      conclusion=failure
    else
      conclusion=success
    fi
    printf '{{"headSha":"{FAKE_HEAD_SHA}","conclusion":"%s","url":"x"}}\\n' "$conclusion"
    ;;
  *"--log"*)
    printf 'job\\tassert\\t2026-08-27T00:00:00Z workflow-result=deny-control-succeeded\\n'
    if test "${{FAKE_DENY_ACCEPTED:-0}}" = 1; then
      marker=deny-unexpected-success
    else
      marker=deny-rejected
    fi
    printf 'job\\tassert\\t2026-08-27T00:00:00Z workflow-result=%s\\n' "$marker"
    ;;
esac
exit 0
""",
        encoding="utf-8",
    )
    git.chmod(0o755)
    gh.chmod(0o755)


def write_first_run_tools(
    tmp_path: Path,
    *,
    service_account_exists: bool = False,
) -> tuple[Path, Path, Path]:
    """Create stateful fake provider CLIs for a WIF transaction."""
    tool_dir = tmp_path / "first-run-bin"
    tool_dir.mkdir()
    command_log = tmp_path / "first-run-gcloud.log"
    service_account_state = tmp_path / "service-account-created"
    gcloud = tool_dir / "gcloud"
    fixture = Path(__file__).parent / "fixtures" / "fake_gcloud.sh"
    _ = shutil.copyfile(
        fixture,
        gcloud,
    )
    gcloud.chmod(0o755)
    if service_account_exists:
        _ = service_account_state.write_text("existing\n", encoding="utf-8")
    write_deny_workflow_tools(tool_dir)
    return tool_dir, command_log, service_account_state


def first_run_environment(tool_dir: Path, command_log: Path, state: Path) -> dict[str, str]:
    """Build the isolated environment for a first-run WIF probe."""
    return {
        "PATH": f"{tool_dir}:{os.environ['PATH']}",
        "FAKE_GCLOUD_LOG": str(command_log),
        "FAKE_SA_STATE": str(state),
        "GCP_PROJECT_ID": "example-project",
        "GCP_REGION": "asia-northeast3",
        "GCP_BILLING_ACCOUNT_ID": "ABC",
    }
