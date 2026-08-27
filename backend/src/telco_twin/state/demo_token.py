"""Opaque epoch-bound demo token with exact RFC8785/HMAC bytes."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum, unique
from typing import Annotated, Final, Literal, NewType, Self, final, override

from pydantic import AfterValidator, Field, ValidationError, model_validator

from telco_twin.domain._contract import ContractId, StrictContract, UtcTimestamp, utc_datetime
from telco_twin.domain._validation import fail_validation
from telco_twin.domain.approval import decode_base64url, encode_base64url
from telco_twin.domain.canonical import canonical_model_bytes
from telco_twin.state.limits import SESSION_TTL_SECONDS

DEMO_TOKEN_DOMAIN: Final = b"telco-twin/demo-token/v1\0"
NONCE_BYTES: Final = 16
TOKEN_PARTS: Final = 2
DemoTokenKey = NewType("DemoTokenKey", bytes)


def _nonce(value: str) -> str:
    if len(decode_base64url(value)) != NONCE_BYTES:
        fail_validation("demo_token_nonce", "demo token nonce must encode 128 bits")
    return value


DemoTokenNonce = Annotated[
    str,
    Field(pattern=r"^[A-Za-z0-9_-]{22}$"),
    AfterValidator(_nonce),
]


class DemoTokenClaims(StrictContract):
    """Exact canonical payload signed into a non-persisted demo token."""

    v: Literal[1]
    session_id: ContractId
    startup_epoch: ContractId
    issued_at: UtcTimestamp
    expires_at: UtcTimestamp
    nonce: DemoTokenNonce

    @model_validator(mode="after")
    def lifetime_is_exact(self) -> Self:
        """Require the fixed fifteen-minute demo lifetime."""
        lifetime = utc_datetime(self.expires_at) - utc_datetime(self.issued_at)
        if lifetime.total_seconds() != SESSION_TTL_SECONDS:
            fail_validation("demo_token_ttl", "demo token TTL must be 15 minutes")
        return self


@dataclass(frozen=True, slots=True)
class DemoTokenIssue:
    """Inputs for one token under a codec-bound startup epoch."""

    session_id: ContractId
    now: datetime
    nonce: bytes


@unique
class DemoTokenFailureCode(StrEnum):
    """Stable cryptographic and epoch token outcomes."""

    INVALID = "demo-token-invalid"
    EXPIRED = "demo-token-expired"
    SESSION_LOST = "demo-session-lost"


@dataclass(frozen=True, slots=True)
class DemoTokenValid:
    """Authenticated current-epoch claims."""

    claims: DemoTokenClaims


@dataclass(frozen=True, slots=True)
class DemoTokenRejected:
    """Fail-closed token validation result."""

    code: DemoTokenFailureCode


type DemoTokenResult = DemoTokenValid | DemoTokenRejected


@unique
class DemoTokenIssueErrorCode(StrEnum):
    """Stable token issuance configuration failures."""

    KEY = "demo-token-key-invalid"
    NONCE = "demo-token-nonce-invalid"
    TIME = "demo-token-time-invalid"


@dataclass(frozen=True, slots=True)
class DemoTokenIssueError(Exception):
    """Caller supplied invalid token issuance material."""

    code: DemoTokenIssueErrorCode

    @override
    def __str__(self) -> str:
        return self.code.value


def encode_demo_token(key: DemoTokenKey, claims: DemoTokenClaims) -> str:
    """Encode the exact canonical payload and domain-separated HMAC."""
    payload = canonical_model_bytes(claims)
    signature = hmac.new(bytes(key), DEMO_TOKEN_DOMAIN + payload, hashlib.sha256).digest()
    return f"{encode_base64url(payload)}.{encode_base64url(signature)}"


def _decode_component(value: str) -> bytes | None:
    if not value or "=" in value:
        return None
    try:
        decoded = base64.urlsafe_b64decode(value + ("=" * (-len(value) % 4)))
    except (binascii.Error, ValueError):
        return None
    if base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != value:
        return None
    return decoded


def _authenticated_claims(key: DemoTokenKey, token: str) -> DemoTokenClaims | None:
    parts = token.split(".")
    if len(parts) != TOKEN_PARTS:
        return None
    payload = _decode_component(parts[0])
    signature = _decode_component(parts[1])
    if payload is None or signature is None:
        return None
    expected = hmac.new(bytes(key), DEMO_TOKEN_DOMAIN + payload, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        claims = DemoTokenClaims.model_validate_json(payload)
    except ValidationError:
        return None
    return claims if canonical_model_bytes(claims) == payload else None


@final
class DemoTokenCodec:
    """Epoch-bound token codec whose signing key is never represented."""

    __slots__ = ("__key", "_startup_epoch")

    def __init__(self, key: DemoTokenKey, startup_epoch: ContractId) -> None:
        """Bind one distinct HMAC key to one process startup epoch."""
        if len(key) < hashlib.sha256().digest_size:
            raise DemoTokenIssueError(DemoTokenIssueErrorCode.KEY)
        self.__key = key
        self._startup_epoch = startup_epoch

    @property
    def startup_epoch(self) -> ContractId:
        """Return the process epoch that distinguishes restarts."""
        return self._startup_epoch

    def issue(self, issue: DemoTokenIssue) -> tuple[str, DemoTokenClaims]:
        """Mint one non-persisted exact-15-minute token."""
        if len(issue.nonce) != NONCE_BYTES:
            raise DemoTokenIssueError(DemoTokenIssueErrorCode.NONCE)
        if issue.now.tzinfo is None or issue.now.utcoffset() is None:
            raise DemoTokenIssueError(DemoTokenIssueErrorCode.TIME)
        issued_at = issue.now.astimezone(UTC)
        claims = DemoTokenClaims(
            v=1,
            session_id=issue.session_id,
            startup_epoch=self._startup_epoch,
            issued_at=issued_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            expires_at=(issued_at + timedelta(seconds=SESSION_TTL_SECONDS)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            nonce=encode_base64url(issue.nonce),
        )
        return encode_demo_token(self.__key, claims), claims

    def validate(self, token: str, now: datetime) -> DemoTokenResult:
        """Authenticate canonical claims, expiry, and startup epoch in that order."""
        claims = _authenticated_claims(self.__key, token)
        if claims is None:
            return DemoTokenRejected(DemoTokenFailureCode.INVALID)
        if now.tzinfo is None or now.utcoffset() is None:
            return DemoTokenRejected(DemoTokenFailureCode.INVALID)
        if now.astimezone(UTC) < utc_datetime(claims.issued_at):
            return DemoTokenRejected(DemoTokenFailureCode.INVALID)
        if now.astimezone(UTC) >= utc_datetime(claims.expires_at):
            return DemoTokenRejected(DemoTokenFailureCode.EXPIRED)
        if claims.startup_epoch != self._startup_epoch:
            return DemoTokenRejected(DemoTokenFailureCode.SESSION_LOST)
        return DemoTokenValid(claims)

    @override
    def __repr__(self) -> str:
        return f"DemoTokenCodec(startup_epoch={self._startup_epoch!r})"
