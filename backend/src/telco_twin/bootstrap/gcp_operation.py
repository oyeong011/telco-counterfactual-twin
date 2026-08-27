"""Typed context shared by one operation-owned GCP mutation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from telco_twin.bootstrap.gcp_commands import GcpContext
    from telco_twin.bootstrap.gcp_ownership import OperationOwnership
    from telco_twin.bootstrap.gcp_reconciliation import ReconciliationPolicy


@dataclass(frozen=True, slots=True)
class GcpOperation:
    """Provider authority, ownership, and reconciliation for one mutation."""

    context: GcpContext
    ownership: OperationOwnership
    policy: ReconciliationPolicy
