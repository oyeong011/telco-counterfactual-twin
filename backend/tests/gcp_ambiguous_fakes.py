"""Stateful GCP fake for server-commit/client-timeout transaction tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from telco_twin.bootstrap.gcp_commands import GcpContext


class AmbiguousTemporaryGcloud:
    """Apply one requested mutation before returning a timeout result."""

    context: GcpContext
    failure_point: str
    commands: list[str]
    failure_triggered: bool
    provider_exists: bool
    provider_id: str
    binding_exists: bool
    topic_exists: bool
    budget_exists: bool
    deny_member: str

    def __init__(self, context: GcpContext, failure_point: str) -> None:
        self.context = context
        self.failure_point = failure_point
        self.commands = []
        self.failure_triggered = False
        self.provider_exists = False
        self.provider_id = ""
        self.binding_exists = False
        self.topic_exists = False
        self.budget_exists = False
        self.deny_member = (
            "principalSet://iam.googleapis.com/projects/"
            f"{context.project_number}/locations/global/workloadIdentityPools/github-actions/"
            "attribute.repository/oyeong011/nonmatching-preflight"
        )

    def _completed(
        self,
        arguments: Sequence[str],
        *,
        returncode: int = 0,
        stdout: str = "",
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(tuple(arguments), returncode, stdout, "")

    def _mutation_result(
        self,
        arguments: Sequence[str],
        operation: str,
    ) -> subprocess.CompletedProcess[str]:
        if self.failure_point == operation and not self.failure_triggered:
            self.failure_triggered = True
            return self._completed(arguments, returncode=124)
        return self._completed(arguments)

    def _provider_json(self, provider_id: str) -> str:
        return json.dumps(
            {
                "name": (
                    f"projects/{self.context.project_number}/locations/global/"
                    f"workloadIdentityPools/github-actions/providers/{provider_id}"
                ),
                "oidc": {"issuerUri": "https://token.actions.githubusercontent.com"},
                "attributeMapping": {
                    "google.subject": "assertion.sub",
                    "attribute.repository": "assertion.repository",
                    "attribute.repository_owner_id": "assertion.repository_owner_id",
                },
                "attributeCondition": ("assertion.repository=='oyeong011/nonmatching-preflight'"),
            }
        )

    def _policy_json(self) -> str:
        bindings: list[dict[str, str | list[str]]] = []
        if self.binding_exists:
            bindings.append(
                {
                    "role": "roles/iam.workloadIdentityUser",
                    "members": [self.deny_member],
                }
            )
        return json.dumps({"bindings": bindings})

    def _budget_json(self, topic: str) -> str:
        return json.dumps(
            {
                "name": f"billingAccounts/{self.context.billing_account_id}/budgets/123",
                "displayName": topic,
                "budgetFilter": {"projects": [f"projects/{self.context.project_number}"]},
                "notificationsRule": {
                    "schemaVersion": "1.0",
                    "pubsubTopic": f"projects/{self.context.project_id}/topics/{topic}",
                },
            }
        )

    def _provider_result(
        self,
        arguments: tuple[str, ...],
        joined: str,
    ) -> subprocess.CompletedProcess[str] | None:
        if "providers list" in joined:
            payload = (
                [json.loads(self._provider_json(self.provider_id))] if self.provider_exists else []
            )
            return self._completed(arguments, stdout=json.dumps(payload))
        if "providers describe" in joined:
            if not self.provider_exists:
                return self._completed(arguments, returncode=1)
            return self._completed(arguments, stdout=self._provider_json(arguments[5]))
        if "providers create-oidc" in joined:
            self.provider_exists = True
            self.provider_id = arguments[5]
            return self._mutation_result(arguments, "provider-create")
        if "providers delete" in joined:
            self.provider_exists = False
            return self._completed(arguments)
        return None

    def _binding_result(
        self,
        arguments: tuple[str, ...],
        joined: str,
    ) -> subprocess.CompletedProcess[str] | None:
        if "service-accounts get-iam-policy" in joined:
            return self._completed(arguments, stdout=self._policy_json())
        if "service-accounts add-iam-policy-binding" in joined:
            self.binding_exists = True
            return self._mutation_result(arguments, "binding-add")
        if "service-accounts remove-iam-policy-binding" in joined:
            self.binding_exists = False
            return self._completed(arguments)
        if "service-accounts set-iam-policy" in joined:
            policy = Path(arguments[-1]).read_text(encoding="utf-8")
            self.binding_exists = self.deny_member in policy
            return self._completed(arguments)
        return None

    def _topic_result(
        self,
        arguments: tuple[str, ...],
        joined: str,
    ) -> subprocess.CompletedProcess[str] | None:
        topic = "twin-preflight-ambiguous"
        resource = f"projects/{self.context.project_id}/topics/{topic}"
        if "pubsub topics list" in joined:
            payload = [{"name": resource}] if self.topic_exists else []
            return self._completed(arguments, stdout=json.dumps(payload))
        if "pubsub topics describe" in joined:
            return self._completed(
                arguments,
                returncode=0 if self.topic_exists else 1,
                stdout=json.dumps({"name": resource}) if self.topic_exists else "",
            )
        if "pubsub topics create" in joined:
            self.topic_exists = True
            return self._mutation_result(arguments, "topic-create")
        if "pubsub topics delete" in joined:
            self.topic_exists = False
            return self._completed(arguments)
        if "pubsub topics get-iam-policy" in joined:
            policy = {
                "bindings": [
                    {
                        "role": "roles/pubsub.publisher",
                        "members": [
                            "serviceAccount:billing-budget-alert@system.gserviceaccount.com"
                        ],
                    }
                ]
            }
            return self._completed(arguments, stdout=json.dumps(policy))
        return None

    def _budget_result(  # noqa: PLR0911
        self,
        arguments: tuple[str, ...],
        joined: str,
    ) -> subprocess.CompletedProcess[str] | None:
        topic = "twin-preflight-ambiguous"
        resource = f"billingAccounts/{self.context.billing_account_id}/budgets/123"
        if "billing budgets list" in joined:
            payload = [json.loads(self._budget_json(topic))] if self.budget_exists else []
            return self._completed(arguments, stdout=json.dumps(payload))
        if "billing budgets create" in joined:
            self.budget_exists = True
            result = self._mutation_result(arguments, "budget-create")
            if result.returncode != 0:
                return result
            return self._completed(arguments, stdout=resource)
        if "billing budgets describe" in joined:
            return self._completed(arguments, stdout=self._budget_json(topic))
        if "billing budgets delete" in joined:
            if self.failure_point == "budget-delete" and not self.failure_triggered:
                self.failure_triggered = True
                return self._completed(arguments, returncode=124)
            self.budget_exists = False
            return self._completed(arguments)
        return None

    def run(self, arguments: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        joined = " ".join(arguments)
        self.commands.append(joined)
        handlers = (
            self._provider_result,
            self._binding_result,
            self._topic_result,
            self._budget_result,
        )
        for handler in handlers:
            result = handler(arguments, joined)
            if result is not None:
                return result
        return self._completed(arguments)
