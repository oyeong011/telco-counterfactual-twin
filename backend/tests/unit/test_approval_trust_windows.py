from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from telco_twin.domain.approval import (
    ContractViolationError,
    validate_approval_chain,
)

from .contract_cases import approval_context, load_approval_bundle


@pytest.mark.parametrize(
    ("now", "expected_code"),
    [
        (datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC), "root-not-yet-valid"),
        (datetime(2027, 1, 1, 0, 0, 0, tzinfo=UTC), "root-expired"),
    ],
)
def test_chain_rejects_context_outside_root_window(
    now: datetime,
    expected_code: str,
) -> None:
    context = replace(approval_context(), now=now)

    with pytest.raises(ContractViolationError) as caught:
        validate_approval_chain(load_approval_bundle().proof, context)

    assert caught.value.code.value == expected_code


def test_chain_rejects_certificate_window_outside_root_window() -> None:
    context = approval_context()
    certificate = context.certificate.model_copy(
        update={
            "issued_at": "2025-12-31T23:59:30Z",
            "expires_at": "2026-01-01T00:00:30Z",
        }
    )

    with pytest.raises(ContractViolationError) as caught:
        validate_approval_chain(
            load_approval_bundle().proof,
            replace(context, certificate=certificate),
        )

    assert caught.value.code.value == "certificate-outside-root-window"


def test_chain_preserves_stable_certificate_future_and_expiry_codes() -> None:
    context = approval_context()
    future = context.certificate.model_copy(
        update={
            "issued_at": "2026-08-27T00:00:10Z",
            "expires_at": "2026-08-27T00:01:10Z",
        }
    )
    expired = context.certificate.model_copy(
        update={
            "issued_at": "2026-08-26T23:59:20Z",
            "expires_at": "2026-08-27T00:00:20Z",
        }
    )

    with pytest.raises(ContractViolationError) as future_error:
        validate_approval_chain(
            load_approval_bundle().proof,
            replace(
                context,
                certificate=future,
                now=datetime(2026, 8, 27, 0, 0, 5, tzinfo=UTC),
            ),
        )
    with pytest.raises(ContractViolationError) as expired_error:
        validate_approval_chain(
            load_approval_bundle().proof,
            replace(context, certificate=expired),
        )

    assert future_error.value.code.value == "certificate-not-yet-valid"
    assert expired_error.value.code.value == "certificate-expired"
