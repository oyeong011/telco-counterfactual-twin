"""GCP fake that mirrors ownership metadata from an ambiguous mutation."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, assert_never, override

from .gcp_ownership_fakes import DelayedForeignGcloud, OwnershipKind

if TYPE_CHECKING:
    import subprocess

    from telco_twin.bootstrap.gcp_commands import GcpContext

MARKER_PATTERN = re.compile(r"^managed-by=telco-twin-preflight;op=(?P<fingerprint>[0-9a-z]{25})$")
type JsonValue = str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None


class DelayedOwnedGcloud(DelayedForeignGcloud):
    """Commit current-run metadata before returning a timeout result."""

    marker: str
    fingerprint: str
    metadata_registered: bool

    def __init__(self, context: GcpContext, kind: OwnershipKind) -> None:
        super().__init__(context, kind)
        self.marker = ""
        self.fingerprint = ""
        self.metadata_registered = False

    def _capture_metadata(self, arguments: tuple[str, ...]) -> None:
        match self.kind:
            case "service-account" | "pool" | "provider":
                value = next(
                    (
                        argument.removeprefix("--description=")
                        for argument in arguments
                        if argument.startswith("--description=")
                    ),
                    "",
                )
                matched = MARKER_PATTERN.fullmatch(value)
            case "topic":
                labels = next(
                    (
                        argument.removeprefix("--labels=")
                        for argument in arguments
                        if argument.startswith("--labels=")
                    ),
                    "",
                )
                label_map = dict(item.split("=", 1) for item in labels.split(",") if "=" in item)
                fingerprint = label_map.get("operation-fingerprint", "")
                value = f"managed-by={label_map.get('managed-by', '')};op={fingerprint}"
                matched = MARKER_PATTERN.fullmatch(value)
            case "budget":
                value = next(
                    (
                        argument.removeprefix("--display-name=")
                        for argument in arguments
                        if argument.startswith("--display-name=")
                    ),
                    "",
                )
                matched = MARKER_PATTERN.fullmatch(value)
            case "binding":
                condition = next(
                    (
                        argument.removeprefix("--condition=")
                        for argument in arguments
                        if argument.startswith("--condition=")
                    ),
                    "",
                )
                title = next(
                    (
                        part.removeprefix("title=")
                        for part in condition.split(",")
                        if part.startswith("title=")
                    ),
                    "",
                )
                description = next(
                    (
                        part.removeprefix("description=")
                        for part in condition.split(",")
                        if part.startswith("description=")
                    ),
                    "",
                )
                value = title
                matched = MARKER_PATTERN.fullmatch(value)
                if description != value or "expression=true" not in condition:
                    matched = None
            case _:
                assert_never(self.kind)
        self.marker = value
        if matched is not None:
            self.fingerprint = matched.group("fingerprint")
            self.metadata_registered = True

    @override
    def _foreign_payload(self) -> str:
        if not self.metadata_registered:
            return super()._foreign_payload()
        match self.kind:
            case "service-account":
                payload: JsonValue = [
                    {
                        "name": (
                            f"projects/{self.context.project_id}/serviceAccounts/"
                            "skt-portfolio-deployer@example-project.iam.gserviceaccount.com"
                        ),
                        "uniqueId": "123456789012345678901",
                        "email": ("skt-portfolio-deployer@example-project.iam.gserviceaccount.com"),
                        "displayName": "SKT Portfolio Deployer",
                        "description": self.marker,
                    }
                ]
            case "pool":
                payload = [
                    {
                        "name": (
                            f"projects/{self.context.project_number}/locations/global/"
                            "workloadIdentityPools/github-actions"
                        ),
                        "displayName": "GitHub Actions",
                        "description": self.marker,
                    }
                ]
            case "provider":
                payload = [
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
                            "attribute.repository_owner_id": "assertion.repository_owner_id",
                        },
                        "attributeCondition": (
                            "assertion.repository=='oyeong011/nonmatching-preflight'"
                        ),
                        "description": self.marker,
                    }
                ]
            case "binding":
                payload = {
                    "bindings": [
                        {
                            "role": "roles/iam.workloadIdentityUser",
                            "members": [self.member],
                            "condition": {
                                "expression": "true",
                                "title": self.marker,
                                "description": self.marker,
                            },
                        }
                    ]
                }
            case "topic":
                payload = [
                    {
                        "name": (
                            f"projects/{self.context.project_id}/topics/twin-preflight-foreign"
                        ),
                        "labels": {
                            "managed-by": "telco-twin-preflight",
                            "operation-fingerprint": self.fingerprint,
                        },
                    }
                ]
            case "budget":
                payload = [
                    {
                        "name": f"billingAccounts/{self.context.billing_account_id}/budgets/123",
                        "displayName": self.marker,
                        "budgetFilter": {"projects": [f"projects/{self.context.project_number}"]},
                        "notificationsRule": {
                            "schemaVersion": "1.0",
                            "pubsubTopic": (
                                f"projects/{self.context.project_id}/topics/twin-preflight-foreign"
                            ),
                        },
                    }
                ]
            case _:
                assert_never(self.kind)
        return json.dumps(payload)

    @override
    def run(
        self,
        arguments: tuple[str, ...],
        *,
        timeout_seconds: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        rendered = " ".join(arguments)
        mutation_markers = {
            "service-account": "service-accounts create",
            "pool": "workload-identity-pools create",
            "provider": "providers create-oidc",
            "binding": "service-accounts add-iam-policy-binding",
            "topic": "pubsub topics create",
            "budget": "billing budgets create",
        }
        if mutation_markers[self.kind] in rendered:
            self._capture_metadata(arguments)
        return super().run(arguments, timeout_seconds=timeout_seconds)
