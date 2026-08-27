from __future__ import annotations

import pytest

from telco_twin.bootstrap import gcp_commands, gcp_resource_probe
from telco_twin.bootstrap.gcp_commands import GcpContext, ProvisioningError
from telco_twin.bootstrap.gcp_reconciliation import ReconciliationPolicy
from telco_twin.bootstrap.probe_errors import ProviderProbeError

from .gcp_ambiguous_fakes import AmbiguousTemporaryGcloud
from .gcp_eventual_fakes import FakeClock

CONTEXT = GcpContext(
    project_id="example-project",
    project_number="987654321",
    billing_account_id="ABC",
    owner_id="12345678",
)
SERVICE_ACCOUNT = "skt-portfolio-deployer@example-project.iam.gserviceaccount.com"


def test_deny_timeout_still_removes_binding_and_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    fake = AmbiguousTemporaryGcloud(CONTEXT, "no-mutation-timeout")
    clock = FakeClock()
    policy = ReconciliationPolicy(monotonic=clock.monotonic, sleeper=clock.sleep)

    def timeout_deny(_provider: str, _service_account: str, _project: str) -> None:
        code = "deny-workflow-timeout"
        raise ProviderProbeError(code)

    monkeypatch.setattr(gcp_commands, "run_gcloud", fake.run)
    monkeypatch.setattr(gcp_resource_probe, "assert_deny_exchange", timeout_deny)

    # When
    with pytest.raises(ProvisioningError, match="deny-workflow-timeout"):
        _ = gcp_resource_probe.run_temporary_probes(
            CONTEXT,
            SERVICE_ACCOUNT,
            "timeout-test",
            policy,
        )

    # Then
    assert fake.binding_exists is False
    assert fake.provider_exists is False
    assert any("service-accounts remove-iam-policy-binding" in command for command in fake.commands)
    assert any(
        "providers delete github-oidc-deny-timeout-test" in command for command in fake.commands
    )
