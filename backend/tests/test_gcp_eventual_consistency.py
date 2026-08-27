from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from telco_twin.bootstrap import gcp_commands, gcp_resource_probe
from telco_twin.bootstrap.gcp_binding import BindingRollbackIntent
from telco_twin.bootstrap.gcp_commands import GcpContext, ProvisioningError
from telco_twin.bootstrap.gcp_iam_contract import IamPolicy
from telco_twin.bootstrap.gcp_ownership import OperationOwnership
from telco_twin.bootstrap.gcp_persistent_contract import PoolRollbackIntent
from telco_twin.bootstrap.gcp_persistent_reconcile import cleanup_pool
from telco_twin.bootstrap.gcp_reconciliation import ReconciliationPolicy
from telco_twin.bootstrap.gcp_resource_contract import (
    BudgetRollbackIntent,
    ProviderRollbackIntent,
    TopicRollbackIntent,
)
from telco_twin.bootstrap.gcp_service_account import ServiceAccountCreateIntent
from telco_twin.bootstrap.gcp_temporary_mutations import (
    cleanup_budget,
    cleanup_provider,
    cleanup_topic,
)

from .gcp_eventual_fakes import EventuallyConsistentGcloud, FakeClock, ResourceKind

if TYPE_CHECKING:
    from collections.abc import Callable

CONTEXT = GcpContext("example-project", "987654321", "ABC", "12345678")
SERVICE_ACCOUNT = "skt-portfolio-deployer@example-project.iam.gserviceaccount.com"
OWNERSHIP = OperationOwnership("a" * 25)


def cleanup(kind: ResourceKind, policy: ReconciliationPolicy) -> bool:
    """Exercise the real rollback boundary for one resource family."""
    operations: dict[ResourceKind, Callable[[], bool]] = {
        "service-account": lambda: ServiceAccountCreateIntent(
            CONTEXT, SERVICE_ACCOUNT, OWNERSHIP, policy
        ).rollback(),
        "pool": lambda: cleanup_pool(PoolRollbackIntent(CONTEXT, OWNERSHIP, policy)),
        "provider": lambda: cleanup_provider(
            ProviderRollbackIntent(
                CONTEXT,
                "github-oidc-deny-eventual",
                "assertion.repository=='oyeong011/nonmatching-preflight'",
                OWNERSHIP,
                policy,
            )
        ),
        "binding": lambda: BindingRollbackIntent(
            SERVICE_ACCOUNT,
            "principalSet://example.invalid/eventual",
            OWNERSHIP,
            IamPolicy(bindings=()),
            policy,
        ).rollback(),
        "topic": lambda: cleanup_topic(
            TopicRollbackIntent(CONTEXT, "twin-preflight-eventual", OWNERSHIP, policy)
        ),
        "budget": lambda: cleanup_budget(
            BudgetRollbackIntent(CONTEXT, "twin-preflight-eventual", OWNERSHIP, policy)
        ),
    }
    return operations[kind]()


@pytest.mark.parametrize(
    "kind",
    ["service-account", "pool", "provider", "binding", "topic", "budget"],
)
def test_delayed_visibility_and_late_cleanup_eventually_converge(
    kind: ResourceKind,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    fake = EventuallyConsistentGcloud(kind, visibility_delay=2, absence_delay=2)
    clock = FakeClock()
    policy = ReconciliationPolicy(monotonic=clock.monotonic, sleeper=clock.sleep)
    monkeypatch.setattr(gcp_commands, "run_gcloud", fake.run)

    # When
    cleaned = cleanup(kind, policy)

    # Then
    assert cleaned is True
    assert fake.mutation_attempted is True
    assert fake.reads_before_mutation >= 3
    assert fake.reads_after_mutation >= 3
    assert fake.read_timeouts
    assert all(timeout == 15.0 for timeout in fake.read_timeouts)
    assert clock.sleeps
    assert max(clock.sleeps) <= 8.0


@pytest.mark.parametrize(
    "kind",
    ["service-account", "pool", "provider", "binding", "topic", "budget"],
)
def test_never_visible_resource_fails_closed(
    kind: ResourceKind,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    fake = EventuallyConsistentGcloud(kind, visibility_delay=10_000, absence_delay=0)
    clock = FakeClock()
    policy = ReconciliationPolicy(monotonic=clock.monotonic, sleeper=clock.sleep)
    monkeypatch.setattr(gcp_commands, "run_gcloud", fake.run)

    # When
    cleaned = cleanup(kind, policy)

    # Then
    assert cleaned is False
    assert fake.mutation_attempted is False
    assert clock.current == 90.0
    assert fake.read_timeouts
    assert all(timeout == 15.0 for timeout in fake.read_timeouts)


@pytest.mark.parametrize(
    "kind",
    ["service-account", "pool", "provider", "binding", "topic", "budget"],
)
def test_never_absent_resource_fails_closed_after_cleanup_attempt(
    kind: ResourceKind,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    fake = EventuallyConsistentGcloud(kind, visibility_delay=0, absence_delay=10_000)
    clock = FakeClock()
    policy = ReconciliationPolicy(monotonic=clock.monotonic, sleeper=clock.sleep)
    monkeypatch.setattr(gcp_commands, "run_gcloud", fake.run)

    # When
    cleaned = cleanup(kind, policy)

    # Then
    assert cleaned is False
    assert fake.mutation_attempted is True
    assert clock.current == 90.0
    assert all(timeout == 15.0 for timeout in fake.read_timeouts)


def test_unresolved_cleanup_raises_stable_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    fake = EventuallyConsistentGcloud(
        "provider",
        visibility_delay=10_000,
        absence_delay=0,
    )
    clock = FakeClock()
    policy = ReconciliationPolicy(monotonic=clock.monotonic, sleeper=clock.sleep)
    monkeypatch.setattr(gcp_commands, "run_gcloud", fake.run)

    # When / Then
    with pytest.raises(ProvisioningError, match="cleanup-unresolved"):
        _ = gcp_resource_probe.run_temporary_probes(
            CONTEXT,
            SERVICE_ACCOUNT,
            "eventual",
            policy,
        )


def test_transient_bounded_read_errors_are_retried() -> None:
    # Given
    clock = FakeClock()
    policy = ReconciliationPolicy(monotonic=clock.monotonic, sleeper=clock.sleep)
    calls = 0

    def read() -> bool:
        nonlocal calls
        calls += 1
        if calls < 3:
            code = "transient-read-failed"
            raise ProvisioningError(code)
        return True

    # When
    result = policy.poll(read, lambda ready: ready)

    # Then
    assert result is True
    assert calls == 3
    assert clock.sleeps == [0.25, 0.5]
