"""Shared trusted-time guard for the exact approval evidence window."""

from __future__ import annotations

from typing import TYPE_CHECKING

from telco_twin.api.errors import ProblemError
from telco_twin.domain._contract import utc_datetime
from telco_twin.state.trusted_clock import trusted_now

if TYPE_CHECKING:
    from telco_twin.api.runtime_models import ApprovalResource
    from telco_twin.approval.authority import SessionApprovalAuthority
    from telco_twin.state.trusted_clock import TrustedClock


def require_open_approval_window(
    resource: ApprovalResource,
    signer: SessionApprovalAuthority,
    clock: TrustedClock,
) -> None:
    """Fail before append when request or certificate evidence time has elapsed."""
    now = trusted_now(clock)
    if now >= min(
        utc_datetime(resource.request.expires_at),
        utc_datetime(signer.certificate.expires_at),
    ):
        raise ProblemError(
            409,
            "approval_window_expired",
            "Approval window expired",
            "The exact approval evidence window has elapsed.",
        )
