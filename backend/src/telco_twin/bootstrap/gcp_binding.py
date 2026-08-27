"""Operation-owned service-account IAM binding mutations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from telco_twin.bootstrap.gcp_commands import ProvisioningError
from telco_twin.bootstrap.gcp_iam_contract import (
    IamBinding,
    IamCondition,
    IamPolicy,
    parse_iam_policy,
)

if TYPE_CHECKING:
    from telco_twin.bootstrap.gcp_operation import GcpOperation
    from telco_twin.bootstrap.gcp_ownership import OperationOwnership
    from telco_twin.bootstrap.gcp_reconciliation import ReconciliationPolicy

WIF_ROLE: Final = "roles/iam.workloadIdentityUser"
CONDITION_EXPRESSION: Final = "true"


def _policy(
    service_account: str,
    policy: ReconciliationPolicy,
) -> IamPolicy | None:
    result = policy.read(
        (
            "gcloud",
            "iam",
            "service-accounts",
            "get-iam-policy",
            service_account,
            "--format=json",
        )
    )
    if result.returncode != 0:
        return None
    try:
        return parse_iam_policy(result.stdout)
    except ProvisioningError:
        return None


@dataclass(frozen=True, slots=True)
class BindingRollbackIntent:
    """Prior IAM state plus an exact current-operation conditional edge."""

    service_account: str
    member: str
    ownership: OperationOwnership
    prior_policy: IamPolicy
    policy: ReconciliationPolicy

    @property
    def condition(self) -> IamCondition:
        """Return the immutable condition identity embedded by this run."""
        return IamCondition(
            expression=CONDITION_EXPRESSION,
            title=self.ownership.marker,
            description=self.ownership.marker,
        )

    @property
    def condition_argument(self) -> str:
        """Return the exact gcloud condition payload for add and remove."""
        marker = self.ownership.marker
        return f"expression={CONDITION_EXPRESSION},title={marker},description={marker}"

    def _current_policy(self) -> IamPolicy | None:
        return _policy(self.service_account, self.policy)

    def matches(self, binding: IamBinding) -> bool:
        """Require role, member, and both condition ownership fields."""
        return (
            binding.role == WIF_ROLE
            and self.member in binding.members
            and binding.condition == self.condition
        )

    def is_visible(self, current: IamPolicy | None) -> bool:
        """Return whether this operation's exact conditional edge exists."""
        return current is not None and any(self.matches(binding) for binding in current.bindings)

    def add(self) -> None:
        """Dispatch the exact binding and reconcile current-run ownership."""
        result = self.policy.read(
            (
                "gcloud",
                "iam",
                "service-accounts",
                "add-iam-policy-binding",
                self.service_account,
                f"--role={WIF_ROLE}",
                f"--member={self.member}",
                f"--condition={self.condition_argument}",
                "--quiet",
            )
        )
        visible = self.policy.poll(self._current_policy, self.is_visible)
        if result.returncode != 0:
            code = "binding-create-failed"
            raise ProvisioningError(code)
        if visible is None:
            code = "binding-ownership-unproven"
            raise ProvisioningError(code)

    def rollback(self) -> bool:
        """Remove only this operation's edge, then require the exact prior state."""
        visible = self.policy.poll(self._current_policy, self.is_visible)
        if visible is None:
            return False
        _ = self.policy.read(
            (
                "gcloud",
                "iam",
                "service-accounts",
                "remove-iam-policy-binding",
                self.service_account,
                f"--role={WIF_ROLE}",
                f"--member={self.member}",
                f"--condition={self.condition_argument}",
                "--quiet",
            )
        )
        restored = self.policy.poll(
            self._current_policy,
            lambda current: current == self.prior_policy,
            confirmations=2,
        )
        return restored is not None


def prepare_binding_intent(
    service_account: str,
    member: str,
    operation: GcpOperation,
) -> BindingRollbackIntent | None:
    """Snapshot IAM and return no mutation when the member already exists."""
    prior = _policy(service_account, operation.policy)
    if prior is None:
        code = "binding-snapshot-failed"
        raise ProvisioningError(code)
    exists = any(
        binding.role == WIF_ROLE and member in binding.members for binding in prior.bindings
    )
    if exists:
        return None
    return BindingRollbackIntent(
        service_account,
        member,
        operation.ownership,
        prior,
        operation.policy,
    )
