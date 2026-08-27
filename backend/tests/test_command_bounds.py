from __future__ import annotations

import os
import subprocess
import time
from typing import TYPE_CHECKING

import pytest

from telco_twin.bootstrap import cloudflare_probe, gcp_commands
from telco_twin.bootstrap.cloudflare_probe import CloudflareContext
from telco_twin.bootstrap.gcp_commands import GcpContext
from telco_twin.bootstrap.gcp_iam_probe import probe_gcp_iam
from telco_twin.bootstrap.gcp_resource_cleanup import (
    TemporaryCleanupPlan,
    cleanup_temporary,
)
from telco_twin.bootstrap.gcp_resource_contract import BudgetCleanupTarget
from telco_twin.bootstrap.probe_errors import ProviderProbeError

from .conftest import run_project_script

if TYPE_CHECKING:
    from pathlib import Path


def write_tool(path: Path, body: str) -> None:
    _ = path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


def test_command_timeout_returns_stable_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    sleeper = tmp_path / "sleeper"
    write_tool(sleeper, "exec sleep 0.5")
    monkeypatch.setattr(
        gcp_commands,
        "DEFAULT_COMMAND_TIMEOUT_SECONDS",
        0.05,
        raising=False,
    )

    # When
    started = time.monotonic()
    result = gcp_commands.run_command((str(sleeper),))
    elapsed = time.monotonic() - started

    # Then
    assert result.returncode == 124
    assert elapsed < 0.2


def test_command_os_error_returns_stable_result() -> None:
    # Given / When
    result = gcp_commands.run_command(("/definitely/missing/twin-command",))

    # Then
    assert result.returncode == 126


def test_provider_and_permission_commands_use_default_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    tool_dir = tmp_path / "bin"
    tool_dir.mkdir()
    write_tool(tool_dir / "gcloud", "exec sleep 0.5")
    write_tool(tool_dir / "wrangler", "exec sleep 0.5")
    monkeypatch.setenv("PATH", f"{tool_dir}:/usr/bin:/bin")
    monkeypatch.setattr(
        gcp_commands,
        "DEFAULT_COMMAND_TIMEOUT_SECONDS",
        0.05,
        raising=False,
    )
    context = GcpContext("example-project", "987654321", "ABC", "12345678")
    api_token = "fabricated" + "-cloudflare-value"
    cloudflare_context = CloudflareContext(
        account_id="account-id",
        api_token=api_token,
        source_sha="a" * 40,
        wrangler_command=str(tool_dir / "wrangler"),
    )

    # When
    started = time.monotonic()
    with pytest.raises(ProviderProbeError, match="gcloud-access-token-failed"):
        _ = probe_gcp_iam(context)
    with pytest.raises(ProviderProbeError, match="cloudflare-deploy-failed"):
        cloudflare_probe.deploy_pages(
            cloudflare_context,
            tmp_path,
            "twin-preflight-test",
        )
    elapsed = time.monotonic() - started

    # Then
    assert elapsed < 0.3


def test_workflow_query_command_uses_explicit_bound(
    tmp_path: Path,
) -> None:
    # Given
    tool_dir = tmp_path / "bin"
    tool_dir.mkdir()
    write_tool(tool_dir / "gh", "exec sleep 0.5")

    # When
    result = run_project_script(
        "wait_workflow.py",
        "--workflow",
        "wif-probe.yml",
        "--expected-head-sha",
        "a" * 40,
        "--timeout-seconds",
        "1",
        "--command-timeout-seconds",
        "0.05",
        environment={"PATH": f"{tool_dir}:{os.environ['PATH']}"},
    )

    # Then
    assert result.returncode == 3
    assert "workflow-query-failed" in result.stderr


def test_cleanup_timeout_records_failure_and_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    commands: list[str] = []

    def fake_runner(arguments: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        rendered = " ".join(arguments)
        commands.append(rendered)
        returncode = 124 if "billing budgets delete" in rendered else 0
        return subprocess.CompletedProcess(arguments, returncode, "", "")

    monkeypatch.setattr(gcp_commands, "run_gcloud", fake_runner)
    context = GcpContext("example-project", "987654321", "ABC", "12345678")
    budget = BudgetCleanupTarget(
        resource_name="billingAccounts/ABC/budgets/123",
        billing_account_id="ABC",
        display_name="twin-preflight-test",
        topic_resource="projects/example-project/topics/twin-preflight-test",
        project_resource="projects/987654321",
    )
    plan = TemporaryCleanupPlan(
        context=context,
        service_account="skt-portfolio-deployer@example-project.iam.gserviceaccount.com",
        budget=budget,
        binding_created=True,
        deny_member="principalSet://example.invalid/member",
        provider_created=True,
        deny_provider="github-oidc-deny-test",
        topic_created=True,
        topic="twin-preflight-test",
    )

    # When
    failures = cleanup_temporary(plan)

    # Then
    assert failures == ("budget",)
    assert any("remove-iam-policy-binding" in command for command in commands)
    assert any("providers delete" in command for command in commands)
    assert any("pubsub topics delete" in command for command in commands)
