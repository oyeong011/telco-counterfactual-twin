from __future__ import annotations

import hashlib

import pytest

from telco_twin.domain import approval
from telco_twin.domain.approval import (
    ContractErrorCode,
    ContractViolationError,
    decode_base64url,
    validate_approval_chain,
)

from .approval_signing import repackaged_production_chain
from .contract_cases import load_approval_bundle


def test_fixture_public_key_fingerprint_is_compiled_into_production_denylist() -> None:
    root = load_approval_bundle().root
    fingerprint = hashlib.sha256(decode_base64url(root.public_key_jwk.x)).hexdigest()

    assert fingerprint in approval.TEST_ONLY_PUBLIC_KEY_FINGERPRINTS


def test_repackaged_test_key_is_rejected_from_complete_production_chain() -> None:
    chain = repackaged_production_chain()

    with pytest.raises(ContractViolationError) as caught:
        validate_approval_chain(chain.proof, chain.context)

    assert caught.value.code is ContractErrorCode.TEST_ROOT_FORBIDDEN
