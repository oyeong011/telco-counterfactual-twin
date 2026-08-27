from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from telco_twin.bootstrap import (
    gcp_persistent,
    gcp_rollback,
    gcp_service_account,
)
from telco_twin.bootstrap.gcp_commands import GcpContext, ProvisioningError

if TYPE_CHECKING:
    from collections.abc import Sequence

ORIGINAL_POLICY = '{"bindings":[{"role":"roles/viewer","members":["user:owner@example.invalid"]}]}'
ORIGINAL_PROVIDER = (
    '{"oidc":{"issuerUri":"https://old.example.invalid"},'
    '"attributeMapping":{"google.subject":"assertion.old"},'
    '"attributeCondition":"assertion.old==true"}'
)
CONTEXT = GcpContext(
    project_id="example-project",
    project_number="987654321",
    billing_account_id="ABC",
    owner_id="12345678",
)


class FakeGcloud:
    """Stateful fake that applies each mutation before its injected failure."""

    commands: list[str]
    service_account_exists: bool
    pool_exists: bool
    provider: str | None
    policy: str
    failure_point: str
    failure_triggered: bool

    def __init__(self, failure_point: str, *, existing: bool) -> None:
        self.commands = []
        self.service_account_exists = existing
        self.pool_exists = existing
        self.provider = ORIGINAL_PROVIDER if existing else None
        self.policy = ORIGINAL_POLICY if existing else '{"bindings":[]}'
        self.failure_point = failure_point
        self.failure_triggered = False

    def _completed(
        self,
        arguments: Sequence[str],
        *,
        returncode: int = 0,
        stdout: str = "",
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(tuple(arguments), returncode, stdout, "")

    def _mutated_result(
        self,
        arguments: Sequence[str],
        operation: str,
    ) -> subprocess.CompletedProcess[str]:
        if self.failure_point == operation and not self.failure_triggered:
            self.failure_triggered = True
            return self._completed(arguments, returncode=1)
        return self._completed(arguments)

    def _service_account_result(
        self,
        arguments: tuple[str, ...],
        joined: str,
    ) -> subprocess.CompletedProcess[str] | None:
        if "service-accounts describe" in joined:
            return self._completed(arguments, returncode=0 if self.service_account_exists else 1)
        if "service-accounts get-iam-policy" in joined:
            return self._completed(arguments, stdout=self.policy)
        if "service-accounts create" in joined:
            self.service_account_exists = True
            return self._completed(arguments)
        if "service-accounts delete" in joined:
            self.service_account_exists = False
            return self._completed(arguments)
        if "service-accounts set-iam-policy" in joined:
            self.policy = Path(arguments[-1]).read_text(encoding="utf-8")
            return self._completed(arguments)
        return None

    def _pool_result(
        self,
        arguments: tuple[str, ...],
        joined: str,
    ) -> subprocess.CompletedProcess[str] | None:
        if "workload-identity-pools describe" in joined and "providers" not in joined:
            return self._completed(arguments, returncode=0 if self.pool_exists else 1)
        if "workload-identity-pools create" in joined and "providers" not in joined:
            self.pool_exists = True
            return self._mutated_result(arguments, "pool-create")
        if "workload-identity-pools delete" in joined and "providers" not in joined:
            self.pool_exists = False
            return self._completed(arguments)
        return None

    def _provider_result(
        self,
        arguments: tuple[str, ...],
        joined: str,
    ) -> subprocess.CompletedProcess[str] | None:
        if "providers describe" in joined:
            if self.provider is None:
                return self._completed(arguments, returncode=1)
            return self._completed(arguments, stdout=self.provider)
        if "providers create-oidc" in joined:
            self.provider = "target"
            return self._mutated_result(arguments, "provider-create")
        if "providers update-oidc" in joined:
            restoring = "--issuer-uri=https://old.example.invalid" in joined
            self.provider = ORIGINAL_PROVIDER if restoring else "target"
            operation = "provider-restore" if restoring else "provider-update"
            return self._mutated_result(arguments, operation)
        if "providers delete" in joined:
            self.provider = None
            return self._completed(arguments)
        return None

    def _binding_result(
        self,
        arguments: tuple[str, ...],
        joined: str,
    ) -> subprocess.CompletedProcess[str] | None:
        if "add-iam-policy-binding" in joined:
            repository = "twin" if "telco-counterfactual-twin" in joined else "evidence-plane"
            self.policy = f"mutated:{repository}"
            return self._mutated_result(arguments, f"binding-{repository}")
        return None

    def run(self, arguments: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        joined = " ".join(arguments)
        self.commands.append(joined)
        handlers = (
            self._service_account_result,
            self._pool_result,
            self._provider_result,
            self._binding_result,
        )
        for handler in handlers:
            result = handler(arguments, joined)
            if result is not None:
                return result
        return self._completed(arguments)

    def require(self, arguments: tuple[str, ...], code: str) -> str:
        result = self.run(arguments)
        if result.returncode != 0:
            raise ProvisioningError(code)
        return result.stdout.strip()

    def attempt(self, arguments: tuple[str, ...]) -> bool:
        return self.run(arguments).returncode == 0


def install_fake(monkeypatch: pytest.MonkeyPatch, fake: FakeGcloud) -> None:
    """Install one stateful fake at every GCP command import seam."""
    monkeypatch.setattr(gcp_persistent, "run_gcloud", fake.run)
    monkeypatch.setattr(gcp_persistent, "require_gcloud", fake.require)
    monkeypatch.setattr(gcp_service_account, "run_gcloud", fake.run)
    monkeypatch.setattr(gcp_service_account, "require_gcloud", fake.require)
    monkeypatch.setattr(gcp_service_account, "attempt_gcloud", fake.attempt)
    monkeypatch.setattr(gcp_rollback, "attempt_gcloud", fake.attempt)


@pytest.mark.parametrize("failure_point", ["pool-create", "provider-create"])
def test_new_persistent_state_is_removed_when_setup_fails(
    failure_point: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    fake = FakeGcloud(failure_point, existing=False)
    install_fake(monkeypatch, fake)

    # When
    with pytest.raises(ProvisioningError):
        _ = gcp_persistent.ensure_persistent(CONTEXT)

    # Then
    assert fake.failure_triggered is True
    assert fake.service_account_exists is False
    assert fake.pool_exists is False
    assert fake.provider is None


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

    # When
    with pytest.raises(ProvisioningError):
        _ = gcp_persistent.ensure_persistent(CONTEXT)

    # Then
    assert fake.failure_triggered is True
    assert fake.service_account_exists is True
    assert fake.pool_exists is True
    assert fake.provider == ORIGINAL_PROVIDER
    assert fake.policy == ORIGINAL_POLICY
