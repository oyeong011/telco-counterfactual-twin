from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING

import pytest

from telco_twin.bootstrap import cloudflare_probe, gcp_commands
from telco_twin.bootstrap.cloudflare_probe import CloudflareContext
from telco_twin.bootstrap.gcp_binding import BindingRollbackIntent
from telco_twin.bootstrap.gcp_commands import GcpContext
from telco_twin.bootstrap.gcp_iam_contract import IamPolicy
from telco_twin.bootstrap.gcp_iam_probe import probe_gcp_iam
from telco_twin.bootstrap.gcp_ownership import OperationOwnership
from telco_twin.bootstrap.gcp_reconciliation import ReconciliationPolicy
from telco_twin.bootstrap.gcp_resource_cleanup import (
    TemporaryCleanupPlan,
    cleanup_temporary,
)
from telco_twin.bootstrap.gcp_resource_contract import (
    BudgetRollbackIntent,
    ProviderRollbackIntent,
    TopicRollbackIntent,
)
from telco_twin.bootstrap.probe_errors import ProviderProbeError

from .conftest import run_project_script
from .gcp_ambiguous_fakes import AmbiguousTemporaryGcloud
from .gcp_eventual_fakes import FakeClock

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
    context = GcpContext("example-project", "987654321", "ABC", "12345678")
    fake = AmbiguousTemporaryGcloud(context, "budget-delete")
    fake.provider_exists = True
    fake.provider_id = "github-oidc-deny-ambiguous"
    fake.binding_exists = True
    fake.topic_exists = True
    fake.budget_exists = True
    ownership = OperationOwnership("a" * 25)
    fake.provider_description = ownership.marker
    fake.binding_condition = {
        "expression": "true",
        "title": ownership.marker,
        "description": ownership.marker,
    }
    fake.topic_labels = {
        "managed-by": "telco-twin-preflight",
        "operation-fingerprint": ownership.fingerprint,
    }
    fake.budget_display_name = ownership.marker
    clock = FakeClock()
    policy = ReconciliationPolicy(monotonic=clock.monotonic, sleeper=clock.sleep)
    monkeypatch.setattr(gcp_commands, "run_gcloud", fake.run)
    plan = TemporaryCleanupPlan(
        budget=BudgetRollbackIntent(
            context,
            "twin-preflight-ambiguous",
            ownership,
            policy,
        ),
        binding=BindingRollbackIntent(
            "skt-portfolio-deployer@example-project.iam.gserviceaccount.com",
            fake.deny_member,
            ownership,
            IamPolicy(bindings=()),
            policy,
        ),
        provider=ProviderRollbackIntent(
            context,
            "github-oidc-deny-ambiguous",
            "assertion.repository=='oyeong011/nonmatching-preflight'",
            ownership,
            policy,
        ),
        topic=TopicRollbackIntent(
            context,
            "twin-preflight-ambiguous",
            ownership,
            policy,
        ),
    )

    # When
    failures = cleanup_temporary(plan)

    # Then
    assert failures == ("budget",)
    assert fake.binding_exists is False
    assert fake.provider_exists is False
    assert fake.topic_exists is False
    assert any("providers delete" in command for command in fake.commands)
    assert any("pubsub topics delete" in command for command in fake.commands)
