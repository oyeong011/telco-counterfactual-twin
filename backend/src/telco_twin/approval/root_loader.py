"""Local fixture and independently trusted production root material loading."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, assert_never

from telco_twin.approval.authority_contracts import (
    AuthorityLoadError,
    AuthorityLoadErrorCode,
    AuthorityMode,
)
from telco_twin.approval.crypto import SigningMaterialError, parse_signing_key
from telco_twin.approval.trust import (
    TrustedRootConfigRejected,
    load_production_trusted_roots,
)
from telco_twin.domain.approval import (
    ContractErrorCode,
    ContractViolationError,
    Environment,
    RootDescriptor,
    encode_base64url,
    validate_root_trust,
)

if TYPE_CHECKING:
    from nacl.signing import SigningKey

TEST_FIXTURES: Final = Path(__file__).resolve().parents[3] / "tests/fixtures/approval"


@dataclass(frozen=True, slots=True)
class RootAuthorityMaterial:
    """Validated public descriptor and matching private signing key."""

    descriptor: RootDescriptor
    signing_key: SigningKey


def _local_material() -> RootAuthorityMaterial:
    descriptor = RootDescriptor.model_validate_json(
        (TEST_FIXTURES / "test-root-descriptor.json").read_bytes()
    )
    key = parse_signing_key((TEST_FIXTURES / "TEST_ONLY_root_private.pem").read_text())
    return RootAuthorityMaterial(descriptor, key)


def _trusted_hashes(descriptor: RootDescriptor) -> frozenset[str]:
    configured = load_production_trusted_roots()
    match configured:
        case TrustedRootConfigRejected():
            hashes: frozenset[str] = frozenset()
        case frozenset() as hashes:
            pass
        case _:  # pragma: no cover - exhaustive typed union
            assert_never(configured)
    try:
        validate_root_trust(descriptor, Environment.PRODUCTION, hashes)
    except ContractViolationError as error:
        code = (
            AuthorityLoadErrorCode.TEST_ROOT_FORBIDDEN
            if error.code is ContractErrorCode.TEST_ROOT_FORBIDDEN
            else AuthorityLoadErrorCode.ROOT_UNTRUSTED
        )
        raise AuthorityLoadError(code) from error
    return hashes


def _production_material(descriptor: RootDescriptor | None) -> RootAuthorityMaterial:
    if descriptor is None:
        raise AuthorityLoadError(AuthorityLoadErrorCode.ROOT_DESCRIPTOR_MISSING)
    _ = _trusted_hashes(descriptor)
    encoded = os.getenv("APPROVAL_ROOT_KEY_SECRET")
    if encoded is None:
        raise AuthorityLoadError(AuthorityLoadErrorCode.ROOT_MATERIAL_MISSING)
    try:
        key = parse_signing_key(encoded)
    except SigningMaterialError as error:
        raise AuthorityLoadError(AuthorityLoadErrorCode.ROOT_MATERIAL_INVALID) from error
    if encode_base64url(bytes(key.verify_key)) != descriptor.public_key_jwk.x:
        raise AuthorityLoadError(AuthorityLoadErrorCode.ROOT_KEY_MISMATCH)
    return RootAuthorityMaterial(descriptor, key)


def load_root_authority_material(
    mode: AuthorityMode,
    descriptor: RootDescriptor | None,
) -> RootAuthorityMaterial:
    """Resolve fixed test material or independently trusted production material."""
    match mode:
        case AuthorityMode.LOCAL | AuthorityMode.CI:
            return _local_material()
        case AuthorityMode.PRODUCTION:
            return _production_material(descriptor)
        case _:  # pragma: no cover - exhaustive enum
            assert_never(mode)
