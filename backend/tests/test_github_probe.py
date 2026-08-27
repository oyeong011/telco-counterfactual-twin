from __future__ import annotations

import os
from typing import TYPE_CHECKING

from telco_twin.bootstrap.preflight_contract import ProbeStatus
from telco_twin.bootstrap.provider_probes import probe_github

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

EXPECTED_SHA = "a" * 40


def test_workflow_runs_query_uses_get_when_form_fields_are_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    tool_dir = tmp_path / "bin"
    tool_dir.mkdir()
    command_log = tmp_path / "gh.log"
    git = tool_dir / "git"
    gh = tool_dir / "gh"
    _ = git.write_text(
        f"#!/bin/sh\nprintf '%s\\t%s\\n' '{EXPECTED_SHA}' 'refs/heads/main'\n",
        encoding="utf-8",
    )
    _ = gh.write_text(
        f"""#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_GH_LOG"
case "$*" in
  *"actions/workflows/wif-probe.yml/runs"*)
    case "$*" in
      *"--method GET"*) printf '%s\\n' '{{"workflow_runs":[{{"head_sha":"{EXPECTED_SHA}"}}]}}' ;;
      *) exit 1 ;;
    esac
    ;;
  *"actions/workflows/wif-probe.yml"*)
    printf '%s\\n' '{{"id":1,"state":"active"}}'
    ;;
  *"collaborators/oyeong011/permission"*)
    printf '%s\\n' '{{"permission":"admin"}}'
    ;;
  *"repos/oyeong011/telco-counterfactual-twin"*)
    printf '%s\\n' \\
      '{{"id":1,"private":false,"fork":false,'\\
      '"default_branch":"main","license":{{"spdx_id":"MIT"}}}}'
    ;;
esac
exit 0
""",
        encoding="utf-8",
    )
    git.chmod(0o755)
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tool_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_GH_LOG", str(command_log))

    # When
    result = probe_github(tmp_path, EXPECTED_SHA, offline=False)

    # Then
    assert result.status is ProbeStatus.READY
    assert "--method GET" in command_log.read_text(encoding="utf-8")
