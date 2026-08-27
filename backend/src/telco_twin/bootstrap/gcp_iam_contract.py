"""Generic typed IAM policy boundary shared by rollback paths."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, ValidationError

from telco_twin.bootstrap.gcp_commands import ProvisioningError


class IamBinding(BaseModel):
    """IAM role and member projection."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    role: str
    members: tuple[str, ...] = ()
    condition: IamCondition | None = None


class IamCondition(BaseModel):
    """Exact condition metadata used to prove one binding mutation."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    expression: str
    title: str
    description: str = ""


class IamPolicy(BaseModel):
    """Generic IAM policy projection."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    bindings: tuple[IamBinding, ...]


def parse_iam_policy(policy: str) -> IamPolicy:
    """Parse a generic IAM policy used for snapshot and reconciliation."""
    try:
        return IamPolicy.model_validate_json(policy)
    except ValidationError:
        code = "iam-policy-invalid"
        raise ProvisioningError(code) from None
