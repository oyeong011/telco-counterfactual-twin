"""Offline EdDSA JWKS validation for explicitly configured approver JWTs."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, ClassVar, Final, Literal

from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from telco_twin.api.errors import ProblemError
from telco_twin.state.trusted_clock import TrustedClock, trusted_now

if TYPE_CHECKING:
    from telco_twin.api.settings import ApiSettings

JWT_PARTS: Final = 3


class _JwtModel(BaseModel):
    """Frozen closed base for JWT and JWKS parsing boundaries."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)


class ApproverJwk(_JwtModel):
    """One supported Ed25519 signing key from configured JWKS."""

    kty: Literal["OKP"]
    crv: Literal["Ed25519"]
    x: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{43}$")]
    kid: str
    alg: Literal["EdDSA"]
    use: Literal["sig"]


class ApproverJwks(_JwtModel):
    """Bounded offline approver key set."""

    keys: Annotated[tuple[ApproverJwk, ...], Field(min_length=1, max_length=16)]


class JwtHeader(_JwtModel):
    """Exact supported JWT protected header."""

    alg: Literal["EdDSA"]
    kid: str
    typ: Literal["JWT"] | None = None


class JwtClaims(_JwtModel):
    """Closed registered and authorization claims for an approver bearer."""

    iss: str
    aud: str | tuple[str, ...]
    exp: int
    iat: int
    sub: str
    nbf: int | None = None
    role: str | None = None
    roles: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class JwtApprover:
    """Configured offline JWT verifier with no network/JWKS fetch surface."""

    issuer: str
    audience: str
    jwks: ApproverJwks
    clock: TrustedClock

    @classmethod
    def from_settings(
        cls,
        settings: ApiSettings,
        clock: TrustedClock,
    ) -> JwtApprover | None:
        """Construct only from the complete all-or-none settings contract."""
        if not settings.jwt_is_configured:
            return None
        if (
            settings.jwt_issuer is None
            or settings.jwt_audience is None
            or settings.jwt_jwks_json is None
        ):
            raise ProblemError(
                503,
                "jwt_config_incomplete",
                "JWT configuration incomplete",
                "Issuer, audience, and JWKS must be configured together.",
            )
        try:
            jwks = ApproverJwks.model_validate_json(settings.jwt_jwks_json)
        except ValidationError as error:
            raise ProblemError(
                503,
                "jwt_jwks_invalid",
                "JWT JWKS invalid",
                "The configured approver JWKS is invalid.",
            ) from error
        return cls(settings.jwt_issuer, settings.jwt_audience, jwks, clock)

    def authenticate(self, authorization: str) -> JwtClaims:
        """Verify canonical EdDSA JWT bytes, registered claims, and approver role."""
        if not authorization.startswith("Bearer "):
            raise _jwt_problem()
        token = authorization.removeprefix("Bearer ")
        parts = token.split(".")
        if len(parts) != JWT_PARTS:
            raise _jwt_problem()
        header_bytes = _decode(parts[0])
        claims_bytes = _decode(parts[1])
        signature = _decode(parts[2])
        if header_bytes is None or claims_bytes is None or signature is None:
            raise _jwt_problem()
        try:
            header = JwtHeader.model_validate_json(header_bytes)
            claims = JwtClaims.model_validate_json(claims_bytes)
        except ValidationError as error:
            raise _jwt_problem() from error
        key = next((candidate for candidate in self.jwks.keys if candidate.kid == header.kid), None)
        if key is None:
            raise _jwt_problem()
        try:
            _ = VerifyKey(_required_decode(key.x)).verify(
                f"{parts[0]}.{parts[1]}".encode(),
                signature,
            )
        except BadSignatureError as error:
            raise _jwt_problem() from error
        now = int(trusted_now(self.clock).timestamp())
        audiences = (claims.aud,) if isinstance(claims.aud, str) else claims.aud
        valid_time = claims.iat <= now < claims.exp and (claims.nbf is None or now >= claims.nbf)
        if claims.iss != self.issuer or self.audience not in audiences or not valid_time:
            raise _jwt_problem()
        if claims.role != "approver" and "approver" not in claims.roles:
            raise ProblemError(
                403,
                "approver_role_required",
                "Approver role required",
                "The verified JWT lacks the approver role.",
            )
        return claims


def _decode(value: str) -> bytes | None:
    if not value or "=" in value:
        return None
    try:
        decoded = base64.urlsafe_b64decode(value + ("=" * (-len(value) % 4)))
    except (binascii.Error, ValueError):
        return None
    canonical = base64.urlsafe_b64encode(decoded).rstrip(b"=").decode()
    return decoded if canonical == value else None


def _required_decode(value: str) -> bytes:
    decoded = _decode(value)
    if decoded is None:
        raise _jwt_problem()
    return decoded


def _jwt_problem() -> ProblemError:
    return ProblemError(
        401, "jwt_approver_invalid", "JWT approver invalid", "The approver JWT is invalid."
    )
