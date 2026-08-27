"""Stateful fake gcloud for persistent WIF rollback tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from telco_twin.bootstrap.gcp_commands import ProvisioningError
from telco_twin.bootstrap.gcp_iam_contract import IamBinding, IamPolicy

if TYPE_CHECKING:
    from collections.abc import Sequence

ORIGINAL_POLICY = '{"bindings":[{"role":"roles/viewer","members":["user:owner@example.invalid"]}]}'
ORIGINAL_PROVIDER = (
    '{"name":"projects/987654321/locations/global/workloadIdentityPools/'
    'github-actions/providers/github-oidc",'
    '"oidc":{"issuerUri":"https://old.example.invalid"},'
    '"attributeMapping":{"google.subject":"assertion.old"},'
    '"attributeCondition":"assertion.old==true"}'
)


class FakeGcloud:
    """Apply each mutation before returning its injected failure."""

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

    def _service_account_result(  # noqa: PLR0911
        self,
        arguments: tuple[str, ...],
        joined: str,
    ) -> subprocess.CompletedProcess[str] | None:
        if "service-accounts describe" in joined:
            return self._completed(arguments, returncode=0 if self.service_account_exists else 1)
        if "service-accounts list" in joined:
            payload = (
                [
                    {
                        "name": (
                            "projects/example-project/serviceAccounts/"
                            "skt-portfolio-deployer@example-project.iam.gserviceaccount.com"
                        ),
                        "email": ("skt-portfolio-deployer@example-project.iam.gserviceaccount.com"),
                        "displayName": "SKT Portfolio Deployer",
                    }
                ]
                if self.service_account_exists
                else []
            )
            return self._completed(arguments, stdout=json.dumps(payload))
        if "service-accounts get-iam-policy" in joined:
            return self._completed(arguments, stdout=self.policy)
        if "service-accounts create" in joined:
            self.service_account_exists = True
            return self._mutated_result(arguments, "service-account-create")
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
        if "workload-identity-pools list" in joined and "providers" not in joined:
            payload = (
                [
                    {
                        "name": (
                            "projects/987654321/locations/global/"
                            "workloadIdentityPools/github-actions"
                        ),
                        "displayName": "GitHub Actions",
                    }
                ]
                if self.pool_exists
                else []
            )
            return self._completed(arguments, stdout=json.dumps(payload))
        if "workload-identity-pools create" in joined and "providers" not in joined:
            self.pool_exists = True
            return self._mutated_result(arguments, "pool-create")
        if "workload-identity-pools delete" in joined and "providers" not in joined:
            self.pool_exists = False
            return self._completed(arguments)
        return None

    def _provider_result(  # noqa: PLR0911
        self,
        arguments: tuple[str, ...],
        joined: str,
    ) -> subprocess.CompletedProcess[str] | None:
        if "providers list" in joined:
            payload = [json.loads(self._provider_json())] if self.provider is not None else []
            return self._completed(arguments, stdout=json.dumps(payload))
        if "providers describe" in joined:
            if self.provider is None:
                return self._completed(arguments, returncode=1)
            return self._completed(arguments, stdout=self._provider_json())
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

    def _provider_json(self) -> str:
        if self.provider == "target":
            return json.dumps(
                {
                    "name": (
                        "projects/987654321/locations/global/workloadIdentityPools/"
                        "github-actions/providers/github-oidc"
                    ),
                    "oidc": {"issuerUri": "https://token.actions.githubusercontent.com"},
                    "attributeMapping": {
                        "google.subject": "assertion.sub",
                        "attribute.repository": "assertion.repository",
                        "attribute.repository_owner_id": "assertion.repository_owner_id",
                    },
                    "attributeCondition": (
                        "assertion.repository_owner_id=='12345678' && assertion.repository in "
                        "['oyeong011/telco-counterfactual-twin',"
                        "'oyeong011/mcp-evidence-plane']"
                    ),
                }
            )
        return ORIGINAL_PROVIDER

    def _binding_result(
        self,
        arguments: tuple[str, ...],
        joined: str,
    ) -> subprocess.CompletedProcess[str] | None:
        if "add-iam-policy-binding" not in joined:
            return None
        repository = "twin" if "telco-counterfactual-twin" in joined else "evidence-plane"
        parsed = IamPolicy.model_validate_json(self.policy)
        binding = IamBinding(
            role="roles/iam.workloadIdentityUser",
            members=(
                next(part.split("=", 1)[1] for part in arguments if part.startswith("--member=")),
            ),
        )
        self.policy = parsed.model_copy(
            update={"bindings": (*parsed.bindings, binding)}
        ).model_dump_json()
        return self._mutated_result(arguments, f"binding-{repository}")

    def run(
        self,
        arguments: tuple[str, ...],
        *,
        timeout_seconds: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        _ = timeout_seconds
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
