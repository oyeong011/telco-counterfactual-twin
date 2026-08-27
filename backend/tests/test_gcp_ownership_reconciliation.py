from __future__ import annotations

from typing import assert_never

import pytest

from telco_twin.bootstrap import gcp_commands, gcp_persistent
from telco_twin.bootstrap.gcp_commands import GcpContext, ProvisioningError
from telco_twin.bootstrap.gcp_operation import GcpOperation
from telco_twin.bootstrap.gcp_ownership import RunOwnership
from telco_twin.bootstrap.gcp_persistent_reconcile import cleanup_pool, prepare_pool
from telco_twin.bootstrap.gcp_reconciliation import ReconciliationPolicy
from telco_twin.bootstrap.gcp_service_account import ensure_service_account
from telco_twin.bootstrap.gcp_temporary_mutations import (
    cleanup_budget,
    cleanup_provider,
    cleanup_topic,
    create_binding,
    create_budget,
    create_provider,
    create_topic,
    prepare_binding,
    prepare_budget,
    prepare_provider,
    prepare_topic,
)

from .gcp_eventual_fakes import FakeClock
from .gcp_owned_mutation_fakes import DelayedOwnedGcloud
from .gcp_ownership_fakes import DelayedForeignGcloud, OwnershipKind

CONTEXT = GcpContext("example-project", "987654321", "ABC", "12345678")
SERVICE_ACCOUNT = "skt-portfolio-deployer@example-project.iam.gserviceaccount.com"
RUN = RunOwnership(b"d" * 32)


def _operation(name: str, policy: ReconciliationPolicy) -> GcpOperation:
    return GcpOperation(CONTEXT, RUN.for_operation(name), policy)


def _attempt_and_cleanup(
    kind: OwnershipKind,
    policy: ReconciliationPolicy,
) -> bool:
    """Dispatch one real mutation path and return its cleanup result."""
    match kind:
        case "pool":
            pool_intent = prepare_pool(_operation("pool", policy))
            with pytest.raises(ProvisioningError):
                gcp_persistent.write_pool(CONTEXT, pool_intent)
            return cleanup_pool(pool_intent)
        case "provider":
            provider_intent = prepare_provider(
                _operation("provider", policy),
                "github-oidc-deny-foreign",
                "assertion.repository=='oyeong011/nonmatching-preflight'",
            )
            with pytest.raises(ProvisioningError):
                create_provider(provider_intent)
            return cleanup_provider(provider_intent)
        case "binding":
            member = "principalSet://example.invalid/delayed-foreign"
            snapshot = prepare_binding(
                SERVICE_ACCOUNT,
                member,
                _operation("binding", policy),
            )
            with pytest.raises(ProvisioningError):
                create_binding(snapshot, member)
            return snapshot.rollback()
        case "topic":
            topic_intent = prepare_topic(
                _operation("topic", policy),
                "twin-preflight-foreign",
            )
            with pytest.raises(ProvisioningError):
                create_topic(topic_intent)
            return cleanup_topic(topic_intent)
        case "budget":
            budget_intent = prepare_budget(
                _operation("budget", policy),
                "twin-preflight-foreign",
            )
            with pytest.raises(ProvisioningError):
                _ = create_budget(budget_intent)
            return cleanup_budget(budget_intent)
        case "service-account":
            message = "service-account uses its self-cleaning path"
            raise AssertionError(message)
        case _:
            assert_never(kind)


@pytest.mark.parametrize(
    "kind",
    ["service-account", "pool", "provider", "binding", "topic", "budget"],
)
def test_delayed_preexisting_resource_is_not_adopted_after_mutation_timeout(
    kind: OwnershipKind,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    fake = DelayedForeignGcloud(CONTEXT, kind)
    clock = FakeClock()
    policy = ReconciliationPolicy(monotonic=clock.monotonic, sleeper=clock.sleep)
    monkeypatch.setattr(gcp_commands, "run_gcloud", fake.run)

    # When
    if kind == "service-account":
        with pytest.raises(ProvisioningError, match="service-account-ownership-conflict"):
            _ = ensure_service_account(CONTEXT, policy)
        cleaned = False
    else:
        cleaned = _attempt_and_cleanup(kind, policy)

    # Then
    assert fake.mutation_attempted is True
    assert cleaned is False
    assert fake.foreign_exists is True, "\n".join(fake.commands)
    assert clock.current >= 90.0
    destructive = (
        "service-accounts delete",
        "workload-identity-pools delete",
        "providers delete",
        "service-accounts set-iam-policy",
        "service-accounts remove-iam-policy-binding",
        "pubsub topics delete",
        "billing budgets delete",
    )
    assert all(not any(marker in command for marker in destructive) for command in fake.commands)


@pytest.mark.parametrize(
    "kind",
    ["service-account", "pool", "provider", "binding", "topic", "budget"],
)
def test_current_operation_fingerprint_is_registered_and_cleaned_after_timeout(
    kind: OwnershipKind,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    fake = DelayedOwnedGcloud(CONTEXT, kind)
    clock = FakeClock()
    policy = ReconciliationPolicy(monotonic=clock.monotonic, sleeper=clock.sleep)
    monkeypatch.setattr(gcp_commands, "run_gcloud", fake.run)

    # When
    if kind == "service-account":
        with pytest.raises(ProvisioningError):
            _ = ensure_service_account(CONTEXT, policy)
        cleaned = not fake.foreign_exists
    else:
        cleaned = _attempt_and_cleanup(kind, policy)

    # Then
    assert fake.mutation_attempted is True
    assert fake.metadata_registered is True, "\n".join(fake.commands)
    assert cleaned is True
    assert fake.foreign_exists is False
