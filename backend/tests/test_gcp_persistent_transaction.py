from __future__ import annotations

import pytest

from telco_twin.bootstrap import gcp_commands, gcp_persistent
from telco_twin.bootstrap.gcp_commands import GcpContext, ProvisioningError
from telco_twin.bootstrap.gcp_reconciliation import ReconciliationPolicy

from .gcp_eventual_fakes import FakeClock
from .gcp_persistent_fakes import (
    ORIGINAL_POLICY,
    ORIGINAL_PROVIDER,
    FakeGcloud,
)

CONTEXT = GcpContext(
    project_id="example-project",
    project_number="987654321",
    billing_account_id="ABC",
    owner_id="12345678",
)


def install_fake(monkeypatch: pytest.MonkeyPatch, fake: FakeGcloud) -> None:
    """Install one stateful fake at every GCP command import seam."""
    monkeypatch.setattr(gcp_commands, "run_gcloud", fake.run)


def assert_reconciled_after_failure(fake: FakeGcloud, failure_point: str) -> None:
    """Require a bounded read after the ambiguous mutation result."""
    markers = {
        "service-account-create": "service-accounts create",
        "pool-create": "workload-identity-pools create",
        "provider-create": "providers create-oidc",
        "provider-update": "providers update-oidc",
        "binding-twin": "telco-counterfactual-twin",
        "binding-evidence-plane": "mcp-evidence-plane",
    }
    mutation_index = next(
        index
        for index, command in enumerate(fake.commands)
        if markers[failure_point] in command
        and (not failure_point.startswith("binding-") or "add-iam-policy-binding" in command)
    )
    subsequent = fake.commands[mutation_index + 1 :]
    if failure_point == "service-account-create":
        assert any(
            "service-accounts describe" in command or "service-accounts list" in command
            for command in subsequent
        )
    elif failure_point == "pool-create":
        assert any(
            (
                "workload-identity-pools describe" in command
                or "workload-identity-pools list" in command
            )
            and "providers" not in command
            for command in subsequent
        )
    elif failure_point.startswith("provider-"):
        assert any(
            "providers describe" in command or "providers list" in command for command in subsequent
        )
    else:
        assert any("service-accounts get-iam-policy" in command for command in subsequent)


@pytest.mark.parametrize(
    "failure_point",
    ["service-account-create", "pool-create", "provider-create"],
)
def test_new_persistent_state_is_removed_when_setup_fails(
    failure_point: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    fake = FakeGcloud(failure_point, existing=False)
    install_fake(monkeypatch, fake)
    clock = FakeClock()
    policy = ReconciliationPolicy(monotonic=clock.monotonic, sleeper=clock.sleep)

    # When
    with pytest.raises(ProvisioningError):
        _ = gcp_persistent.ensure_persistent(CONTEXT, policy)

    # Then
    assert fake.failure_triggered is True
    assert fake.service_account_exists is False
    assert fake.pool_exists is False
    assert fake.provider is None
    assert_reconciled_after_failure(fake, failure_point)


@pytest.mark.parametrize(
    "failure_point",
    ["provider-update", "binding-twin", "binding-evidence-plane"],
)
def test_existing_persistent_state_is_restored_when_setup_fails(
    failure_point: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    fake = FakeGcloud(failure_point, existing=True)
    install_fake(monkeypatch, fake)
    clock = FakeClock()
    policy = ReconciliationPolicy(monotonic=clock.monotonic, sleeper=clock.sleep)

    # When
    with pytest.raises(ProvisioningError):
        _ = gcp_persistent.ensure_persistent(CONTEXT, policy)

    # Then
    assert fake.failure_triggered is True
    assert fake.service_account_exists is True
    assert fake.pool_exists is True
    assert fake.provider == ORIGINAL_PROVIDER
    assert fake.policy == ORIGINAL_POLICY
    assert_reconciled_after_failure(fake, failure_point)
