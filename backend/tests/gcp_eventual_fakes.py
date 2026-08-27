"""Deterministic eventual-consistency clocks and GCP read-back fake."""

from __future__ import annotations

import json
import subprocess
from typing import Final, Literal

type ResourceKind = Literal["service-account", "pool", "provider", "binding", "topic", "budget"]

MARKERS: Final[dict[ResourceKind, tuple[str, str]]] = {
    "service-account": ("service-accounts list", "service-accounts delete"),
    "pool": ("workload-identity-pools list", "workload-identity-pools delete"),
    "provider": ("providers list", "providers delete"),
    "binding": ("service-accounts get-iam-policy", "service-accounts set-iam-policy"),
    "topic": ("pubsub topics list", "pubsub topics delete"),
    "budget": ("billing budgets list", "billing budgets delete"),
}

VISIBLE_PAYLOADS: Final[dict[ResourceKind, str]] = {
    "service-account": json.dumps(
        [
            {
                "name": (
                    "projects/example-project/serviceAccounts/"
                    "skt-portfolio-deployer@example-project.iam.gserviceaccount.com"
                ),
                "email": "skt-portfolio-deployer@example-project.iam.gserviceaccount.com",
                "displayName": "SKT Portfolio Deployer",
            }
        ]
    ),
    "pool": json.dumps(
        [
            {
                "name": (
                    "projects/987654321/locations/global/workloadIdentityPools/github-actions"
                ),
                "displayName": "GitHub Actions",
            }
        ]
    ),
    "provider": json.dumps(
        [
            {
                "name": (
                    "projects/987654321/locations/global/workloadIdentityPools/"
                    "github-actions/providers/github-oidc-deny-eventual"
                ),
                "oidc": {"issuerUri": "https://token.actions.githubusercontent.com"},
                "attributeMapping": {
                    "google.subject": "assertion.sub",
                    "attribute.repository": "assertion.repository",
                    "attribute.repository_owner_id": "assertion.repository_owner_id",
                },
                "attributeCondition": ("assertion.repository=='oyeong011/nonmatching-preflight'"),
            }
        ]
    ),
    "binding": json.dumps(
        {
            "bindings": [
                {
                    "role": "roles/iam.workloadIdentityUser",
                    "members": ["principalSet://example.invalid/eventual"],
                }
            ]
        }
    ),
    "topic": json.dumps([{"name": "projects/example-project/topics/twin-preflight-eventual"}]),
    "budget": json.dumps(
        [
            {
                "name": "billingAccounts/ABC/budgets/123",
                "displayName": "twin-preflight-eventual",
                "budgetFilter": {"projects": ["projects/987654321"]},
                "notificationsRule": {
                    "schemaVersion": "1.0",
                    "pubsubTopic": ("projects/example-project/topics/twin-preflight-eventual"),
                },
            }
        ]
    ),
}


class FakeClock:
    """Advance only when the injected sleeper is called."""

    current: float
    sleeps: list[float]

    def __init__(self) -> None:
        self.current = 0.0
        self.sleeps = []

    def monotonic(self) -> float:
        """Return deterministic monotonic time."""
        return self.current

    def sleep(self, seconds: float) -> None:
        """Advance time without a real wait."""
        self.sleeps.append(seconds)
        self.current += seconds


class EventuallyConsistentGcloud:
    """Hide a committed resource, then delay observation of its cleanup."""

    kind: ResourceKind
    visibility_delay: int
    absence_delay: int
    reads_before_mutation: int
    reads_after_mutation: int
    mutation_attempted: bool
    commands: list[str]
    read_timeouts: list[float | None]

    def __init__(
        self,
        kind: ResourceKind,
        *,
        visibility_delay: int,
        absence_delay: int,
    ) -> None:
        self.kind = kind
        self.visibility_delay = visibility_delay
        self.absence_delay = absence_delay
        self.reads_before_mutation = 0
        self.reads_after_mutation = 0
        self.mutation_attempted = False
        self.commands = []
        self.read_timeouts = []

    def _markers(self) -> tuple[str, str]:
        return MARKERS[self.kind]

    def _visible_payload(self) -> str:
        return VISIBLE_PAYLOADS[self.kind]

    def _absent_payload(self) -> str:
        return '{"bindings":[]}' if self.kind == "binding" else "[]"

    def run(
        self,
        arguments: tuple[str, ...],
        *,
        timeout_seconds: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Return stale reads around a timeout-returning mutation."""
        rendered = " ".join(arguments)
        self.commands.append(rendered)
        read_marker, mutation_marker = self._markers()
        if mutation_marker in rendered:
            self.mutation_attempted = True
            return subprocess.CompletedProcess(arguments, 124, "", "")
        if read_marker not in rendered:
            return subprocess.CompletedProcess(arguments, 0, "", "")
        self.read_timeouts.append(timeout_seconds)
        if not self.mutation_attempted:
            self.reads_before_mutation += 1
            visible = self.reads_before_mutation > self.visibility_delay
        else:
            self.reads_after_mutation += 1
            visible = self.reads_after_mutation <= self.absence_delay
        payload = self._visible_payload() if visible else self._absent_payload()
        return subprocess.CompletedProcess(arguments, 0, payload, "")
