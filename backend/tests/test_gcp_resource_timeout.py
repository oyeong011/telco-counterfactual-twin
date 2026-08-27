from __future__ import annotations

import pytest

from telco_twin.bootstrap import gcp_resource_cleanup, gcp_resource_probe
from telco_twin.bootstrap.gcp_commands import GcpContext, ProvisioningError
from telco_twin.bootstrap.probe_errors import ProviderProbeError

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
    cleanup_commands: list[tuple[str, ...]] = []

    def require_gcloud(_arguments: tuple[str, ...], _code: str) -> str:
        return ""

    def timeout_deny(_provider: str, _service_account: str, _project: str) -> None:
        code = "deny-workflow-timeout"
        raise ProviderProbeError(code)

    def attempt_gcloud(arguments: tuple[str, ...]) -> bool:
        cleanup_commands.append(arguments)
        return True

    monkeypatch.setattr(gcp_resource_probe, "require_gcloud", require_gcloud)
    monkeypatch.setattr(gcp_resource_probe, "assert_deny_exchange", timeout_deny)
    monkeypatch.setattr(gcp_resource_cleanup, "attempt_gcloud", attempt_gcloud)

    # When
    with pytest.raises(ProvisioningError, match="deny-workflow-timeout"):
        _ = gcp_resource_probe.run_temporary_probes(
            CONTEXT,
            SERVICE_ACCOUNT,
            "timeout-test",
        )

    # Then
    rendered = tuple(" ".join(command) for command in cleanup_commands)
    assert any("remove-iam-policy-binding" in command for command in rendered)
    assert any("providers delete github-oidc-deny-timeout-test" in command for command in rendered)
