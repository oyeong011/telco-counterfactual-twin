from __future__ import annotations

import pytest

from telco_twin.bootstrap import gcp_commands, gcp_resource_probe
from telco_twin.bootstrap.gcp_commands import GcpContext, ProvisioningError
from telco_twin.bootstrap.gcp_reconciliation import ReconciliationPolicy
from telco_twin.bootstrap.github_deny_probe import DenyExchangeReceipt
from telco_twin.bootstrap.preflight_contract import receipt_for

from .gcp_ambiguous_fakes import AmbiguousTemporaryGcloud
from .gcp_eventual_fakes import FakeClock

CONTEXT = GcpContext(
    project_id="example-project",
    project_number="987654321",
    billing_account_id="ABC",
    owner_id="12345678",
)
SERVICE_ACCOUNT = "skt-portfolio-deployer@example-project.iam.gserviceaccount.com"


@pytest.mark.parametrize(
    "failure_point",
    ["provider-create", "binding-add", "topic-create", "budget-create"],
)
def test_server_committed_temporary_mutation_is_cleaned_after_client_timeout(
    failure_point: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    fake = AmbiguousTemporaryGcloud(CONTEXT, failure_point)
    clock = FakeClock()
    policy = ReconciliationPolicy(monotonic=clock.monotonic, sleeper=clock.sleep)

    def deny_exchange(
        _provider: str,
        _service_account: str,
        _project: str,
    ) -> DenyExchangeReceipt:
        return DenyExchangeReceipt(
            run_id=1,
            head_sha="a" * 40,
            run_url="https://example.invalid/runs/1",
            evidence=receipt_for("deny-exchange-fixture"),
        )

    monkeypatch.setattr(gcp_commands, "run_gcloud", fake.run)
    monkeypatch.setattr(gcp_resource_probe, "assert_deny_exchange", deny_exchange)

    # When
    with pytest.raises(ProvisioningError):
        _ = gcp_resource_probe.run_temporary_probes(
            CONTEXT,
            SERVICE_ACCOUNT,
            "ambiguous",
            policy,
        )

    # Then
    assert fake.failure_triggered is True
    assert fake.provider_exists is False
    assert fake.binding_exists is False, "\n".join(fake.commands)
    assert fake.topic_exists is False
    assert fake.budget_exists is False, "\n".join(fake.commands)


@pytest.mark.parametrize("preexisting", ["provider", "binding", "topic", "budget"])
def test_preexisting_temporary_authority_is_never_deleted(
    preexisting: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    fake = AmbiguousTemporaryGcloud(CONTEXT, "no-timeout")
    clock = FakeClock()
    policy = ReconciliationPolicy(monotonic=clock.monotonic, sleeper=clock.sleep)
    fake.provider_exists = preexisting == "provider"
    fake.provider_id = "github-oidc-deny-ambiguous"
    fake.binding_exists = preexisting == "binding"
    fake.topic_exists = preexisting == "topic"
    fake.budget_exists = preexisting == "budget"

    def deny_exchange(
        _provider: str,
        _service_account: str,
        _project: str,
    ) -> DenyExchangeReceipt:
        return DenyExchangeReceipt(
            run_id=1,
            head_sha="a" * 40,
            run_url="https://example.invalid/runs/1",
            evidence=receipt_for("deny-exchange-fixture"),
        )

    monkeypatch.setattr(gcp_commands, "run_gcloud", fake.run)
    monkeypatch.setattr(gcp_resource_probe, "assert_deny_exchange", deny_exchange)

    # When
    with pytest.raises(ProvisioningError):
        _ = gcp_resource_probe.run_temporary_probes(
            CONTEXT,
            SERVICE_ACCOUNT,
            "ambiguous",
            policy,
        )

    # Then
    states = {
        "provider": fake.provider_exists,
        "binding": fake.binding_exists,
        "topic": fake.topic_exists,
        "budget": fake.budget_exists,
    }
    assert states[preexisting] is True
    delete_marker = {
        "provider": "providers delete",
        "binding": "set-iam-policy",
        "topic": "pubsub topics delete",
        "budget": "billing budgets delete",
    }[preexisting]
    assert all(delete_marker not in command for command in fake.commands)
