"""Construction of complete provider results from explicit evidence facts."""

from __future__ import annotations

from dataclasses import dataclass

from telco_twin.bootstrap.preflight_contract import (
    EXPECTED_PERMISSIONS,
    CleanupStatus,
    PermissionResult,
    ProbeStatus,
    ProviderName,
    ProviderResult,
    receipt_for,
)


@dataclass(frozen=True, slots=True)
class ProviderFacts:
    """Permission, blocker, cleanup, and receipt inputs for one provider."""

    provider: ProviderName
    granted_permissions: frozenset[str]
    blockers: tuple[str, ...]
    cleanup: CleanupStatus
    seed: str


def make_provider(facts: ProviderFacts) -> ProviderResult:
    """Build a complete provider result, ready only when every gate is satisfied."""
    permissions = tuple(
        PermissionResult(
            permission=permission,
            granted=permission in facts.granted_permissions,
            status=(
                ProbeStatus.READY
                if permission in facts.granted_permissions
                else ProbeStatus.BLOCKED
            ),
            evidence=receipt_for(
                facts.provider,
                permission,
                str(permission in facts.granted_permissions),
                facts.seed,
            ),
        )
        for permission in EXPECTED_PERMISSIONS[facts.provider]
    )
    cleanup_ready = facts.cleanup in {CleanupStatus.CLEAN, CleanupStatus.RESTORED}
    ready = (
        len(facts.granted_permissions) == len(permissions) and not facts.blockers and cleanup_ready
    )
    status = ProbeStatus.READY if ready else ProbeStatus.BLOCKED
    return ProviderResult(
        provider=facts.provider,
        status=status,
        permissions=permissions,
        blockers=facts.blockers,
        cleanup=facts.cleanup,
        evidence=receipt_for(facts.provider, status, facts.seed),
    )


def blocked_provider(provider: ProviderName, blockers: tuple[str, ...]) -> ProviderResult:
    """Represent unavailable authority without claiming a permission probe ran."""
    return make_provider(
        ProviderFacts(
            provider=provider,
            granted_permissions=frozenset(),
            blockers=blockers,
            cleanup=CleanupStatus.NOT_CREATED,
            seed="blocked",
        )
    )
