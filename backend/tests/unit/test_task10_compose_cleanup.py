from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[3]


def _committed_build_sha() -> str:
    """Read the identity the wrapper is expected to derive.

    Pinning a literal SHA here breaks on the next source commit even though the
    wrapper is correct, so the expectation follows the committed build-info the
    wrapper actually reads.
    """
    text = (ROOT / "frontend/public/build-info.json").read_text()
    build_info = cast("dict[str, object]", json.loads(text))
    return str(build_info["runtime_source_commit_sha"])


EXPECTED_BUILD_SHA = _committed_build_sha()


def fake_docker(tmp_path: Path, *, down_status: int = 0) -> tuple[Path, Path]:
    binary = tmp_path / "fake-docker"
    log = tmp_path / "docker.log"
    identity_log = (
        "printf 'source=%s release=%s\\n' "
        f'"$TWIN_RUNTIME_SOURCE_COMMIT_SHA" "$TWIN_RELEASE_COMMIT_SHA" >> \'{log}\''
    )
    script = "\n".join(
        [
            "#!/bin/sh",
            f"printf '%s\\n' \"$*\" >> '{log}'",
            identity_log,
            'case "$*" in',
            "  *' ps --services') exit 0 ;;",
            f"  *' down -v --remove-orphans') exit {down_status} ;;",
            "esac",
            "exit 0",
            "",
        ]
    )
    _ = binary.write_text(script)
    binary.chmod(0o755)
    return binary, log


def invoke(
    tmp_path: Path,
    body: list[str],
    *,
    down_status: int = 0,
) -> tuple[subprocess.CompletedProcess[str], str]:
    binary, log = fake_docker(tmp_path, down_status=down_status)
    env = {**os.environ, "DOCKER_BIN": str(binary)}
    result = subprocess.run(
        [
            str(ROOT / "scripts/with_compose_cleanup.sh"),
            "-f",
            "base.yml",
            "-f",
            "override.yml",
            "backend",
            "--",
            *body,
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    return result, log.read_text() if log.exists() else ""


def invoke_without_services(tmp_path: Path) -> tuple[subprocess.CompletedProcess[str], str]:
    binary, log = fake_docker(tmp_path)
    env = {**os.environ, "DOCKER_BIN": str(binary)}
    _ = env.pop("TWIN_RUNTIME_SOURCE_COMMIT_SHA", None)
    _ = env.pop("TWIN_RELEASE_COMMIT_SHA", None)
    result = subprocess.run(
        [
            str(ROOT / "scripts/with_compose_cleanup.sh"),
            "-f",
            "compose.yml",
            "--",
            "sh",
            "-c",
            "exit 0",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    return result, log.read_text()


def invoke_script_from_cwd(
    tmp_path: Path, script: Path, cwd: Path
) -> tuple[subprocess.CompletedProcess[str], str]:
    binary, log = fake_docker(tmp_path)
    env = {**os.environ, "DOCKER_BIN": str(binary)}
    _ = env.pop("TWIN_RUNTIME_SOURCE_COMMIT_SHA", None)
    _ = env.pop("TWIN_RELEASE_COMMIT_SHA", None)
    result = subprocess.run(
        [
            str(script),
            "-f",
            "compose.yml",
            "--",
            "sh",
            "-c",
            "exit 0",
        ],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    return result, log.read_text() if log.exists() else ""


def test_wrapper_derives_build_identity_from_script_root_not_caller_cwd(
    tmp_path: Path,
) -> None:
    # Given: the wrapper is invoked by absolute path from an unrelated directory.
    unrelated_cwd = tmp_path / "unrelated cwd"
    unrelated_cwd.mkdir()
    # When: the wrapper starts Compose.
    result, log = invoke_script_from_cwd(
        tmp_path, ROOT / "scripts/with_compose_cleanup.sh", unrelated_cwd
    )
    # Then: it still derives both runtime identities from the repo build-info.
    assert result.returncode == 0
    assert f"source={EXPECTED_BUILD_SHA} release={EXPECTED_BUILD_SHA}" in log


def test_wrapper_rejects_missing_build_info_before_starting_compose(
    tmp_path: Path,
) -> None:
    # Given: a wrapper copy whose script root has no frontend build-info.
    repo = tmp_path / "repo copy"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    script = scripts / "with_compose_cleanup.sh"
    _ = shutil.copy(ROOT / "scripts/with_compose_cleanup.sh", script)
    unrelated_cwd = tmp_path / "caller cwd"
    unrelated_cwd.mkdir()
    # When: the wrapper tries to derive the release identity.
    result, log = invoke_script_from_cwd(tmp_path, script, unrelated_cwd)
    # Then: it exits as a usage/configuration error before invoking Docker.
    assert result.returncode == 2
    assert "compose-wrapper-error:invalid-build-identity:runtime_source_commit_sha" in result.stderr
    assert log == ""


def test_wrapper_allows_no_explicit_services(tmp_path: Path) -> None:
    # Given: no service filters before --.
    # When: the wrapper starts Compose.
    result, log = invoke_without_services(tmp_path)
    # Then: it starts the whole compose file and still runs cleanup.
    assert result.returncode == 0
    assert "compose -f compose.yml up -d --build" in log
    assert "compose -f compose.yml down -v --remove-orphans" in log


def test_wrapper_derives_build_identity_from_frontend_artifact(tmp_path: Path) -> None:
    # Given: callers do not provide source/release identity env values.
    # When: the wrapper starts Compose.
    result, log = invoke_without_services(tmp_path)
    # Then: fake Docker receives the source identity from the generated UI build-info.
    assert result.returncode == 0
    assert (f"source={EXPECTED_BUILD_SHA} release={EXPECTED_BUILD_SHA}") in log


def test_wrapper_uses_configured_docker_binary_and_cleans(tmp_path: Path) -> None:
    # Given: a fake Docker binary selected through DOCKER_BIN.
    # When: the wrapped body fails after Compose starts.
    result, log = invoke(tmp_path, ["sh", "-c", "exit 17"])
    # Then: body status wins and cleanup uses the same compose file arguments.
    assert result.returncode == 17
    assert "compose -f base.yml -f override.yml up -d --build backend" in log
    assert "compose -f base.yml -f override.yml down -v --remove-orphans" in log


def test_wrapper_rejects_missing_body_before_starting_compose(tmp_path: Path) -> None:
    # Given: a fake Docker binary that records invocations.
    # When: the wrapper has no command after --.
    result, log = invoke(tmp_path, [])
    # Then: it fails as a usage error without starting the stack.
    assert result.returncode == 2
    assert "compose-wrapper-error:missing-body" in result.stderr
    assert log == ""


def test_wrapper_reports_cleanup_status_after_success(tmp_path: Path) -> None:
    # Given: a successful body and a failing Compose cleanup.
    # When: the wrapper exits.
    result, _ = invoke(tmp_path, ["sh", "-c", "exit 0"], down_status=23)
    # Then: cleanup status is the process status.
    assert result.returncode == 23
    assert "body_status=0 cleanup_status=23" in result.stderr


def test_wrapper_prefers_body_status_when_cleanup_also_fails(tmp_path: Path) -> None:
    # Given: both wrapped body and cleanup fail.
    # When: the wrapper exits.
    result, _ = invoke(tmp_path, ["sh", "-c", "exit 17"], down_status=23)
    # Then: the body status remains the externally visible failure.
    assert result.returncode == 17
    assert "body_status=17 cleanup_status=23" in result.stderr
