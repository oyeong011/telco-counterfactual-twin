"""GCP fake that reveals a delayed foreign resource after mutation dispatch."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Literal, assert_never

if TYPE_CHECKING:
    from collections.abc import Sequence

    from telco_twin.bootstrap.gcp_commands import GcpContext

type OwnershipKind = Literal["service-account", "pool", "provider", "binding", "topic", "budget"]


class DelayedForeignGcloud:
    """Hide one foreign resource until an attempted create returns timeout."""

    context: GcpContext
    kind: OwnershipKind
    mutation_attempted: bool
    foreign_exists: bool
    commands: list[str]
    member: str

    def __init__(self, context: GcpContext, kind: OwnershipKind) -> None:
        self.context = context
        self.kind = kind
        self.mutation_attempted = False
        self.foreign_exists = False
        self.commands = []
        self.member = "principalSet://example.invalid/delayed-foreign"

    @staticmethod
    def _completed(
        arguments: Sequence[str],
        *,
        returncode: int = 0,
        stdout: str = "",
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(tuple(arguments), returncode, stdout, "")

    def _foreign_payload(self) -> str:
        match self.kind:
            case "service-account":
                return json.dumps(
                    [
                        {
                            "name": (
                                f"projects/{self.context.project_id}/serviceAccounts/"
                                "skt-portfolio-deployer@example-project.iam.gserviceaccount.com"
                            ),
                            "uniqueId": "999999999999999999999",
                            "email": (
                                "skt-portfolio-deployer@example-project.iam.gserviceaccount.com"
                            ),
                            "displayName": "SKT Portfolio Deployer",
                        }
                    ]
                )
            case "pool":
                return json.dumps(
                    [
                        {
                            "name": (
                                f"projects/{self.context.project_number}/locations/global/"
                                "workloadIdentityPools/github-actions"
                            ),
                            "displayName": "GitHub Actions",
                        }
                    ]
                )
            case "provider":
                return json.dumps(
                    [
                        {
                            "name": (
                                f"projects/{self.context.project_number}/locations/global/"
                                "workloadIdentityPools/github-actions/providers/"
                                "github-oidc-deny-foreign"
                            ),
                            "oidc": {"issuerUri": "https://token.actions.githubusercontent.com"},
                            "attributeMapping": {
                                "google.subject": "assertion.sub",
                                "attribute.repository": "assertion.repository",
                                "attribute.repository_owner_id": ("assertion.repository_owner_id"),
                            },
                            "attributeCondition": (
                                "assertion.repository=='oyeong011/nonmatching-preflight'"
                            ),
                        }
                    ]
                )
            case "binding":
                return json.dumps(
                    {
                        "bindings": [
                            {
                                "role": "roles/iam.workloadIdentityUser",
                                "members": [self.member],
                            }
                        ]
                    }
                )
            case "topic":
                return json.dumps(
                    [
                        {
                            "name": (
                                f"projects/{self.context.project_id}/topics/twin-preflight-foreign"
                            )
                        }
                    ]
                )
            case "budget":
                return json.dumps(
                    [
                        {
                            "name": (
                                f"billingAccounts/{self.context.billing_account_id}/budgets/123"
                            ),
                            "displayName": "twin-preflight-foreign",
                            "budgetFilter": {
                                "projects": [f"projects/{self.context.project_number}"]
                            },
                            "notificationsRule": {
                                "schemaVersion": "1.0",
                                "pubsubTopic": (
                                    f"projects/{self.context.project_id}/topics/"
                                    "twin-preflight-foreign"
                                ),
                            },
                        }
                    ]
                )
            case _:
                assert_never(self.kind)

    def _read_result(
        self,
        arguments: tuple[str, ...],
    ) -> subprocess.CompletedProcess[str]:
        if self.kind == "binding":
            stdout = self._foreign_payload() if self.foreign_exists else '{"bindings":[]}'
        else:
            stdout = self._foreign_payload() if self.foreign_exists else "[]"
        return self._completed(arguments, stdout=stdout)

    def run(
        self,
        arguments: tuple[str, ...],
        *,
        timeout_seconds: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Return one stale absence, then foreign state after a timeout."""
        _ = timeout_seconds
        rendered = " ".join(arguments)
        self.commands.append(rendered)
        if "service-accounts describe" in rendered:
            return self._completed(arguments, returncode=1)
        read_markers = {
            "service-account": "service-accounts list",
            "pool": "workload-identity-pools list",
            "provider": "providers list",
            "binding": "service-accounts get-iam-policy",
            "topic": "pubsub topics list",
            "budget": "billing budgets list",
        }
        if read_markers[self.kind] in rendered:
            return self._read_result(arguments)
        mutation_markers = {
            "service-account": "service-accounts create",
            "pool": "workload-identity-pools create",
            "provider": "providers create-oidc",
            "binding": "service-accounts add-iam-policy-binding",
            "topic": "pubsub topics create",
            "budget": "billing budgets create",
        }
        if mutation_markers[self.kind] in rendered:
            self.mutation_attempted = True
            self.foreign_exists = True
            return self._completed(arguments, returncode=124)
        destructive_markers = (
            "service-accounts delete",
            "workload-identity-pools delete",
            "providers delete",
            "service-accounts set-iam-policy",
            "service-accounts remove-iam-policy-binding",
            "pubsub topics delete",
            "billing budgets delete",
        )
        if any(marker in rendered for marker in destructive_markers):
            self.foreign_exists = False
            if "set-iam-policy" in rendered:
                _ = Path(arguments[-1]).read_text(encoding="utf-8")
            return self._completed(arguments)
        return self._completed(arguments)
