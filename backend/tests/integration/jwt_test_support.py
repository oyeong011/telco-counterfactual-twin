"""Configured EdDSA JWT fixtures shared by approval integration tests."""

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from telco_twin.api.settings import ApiSettings


@dataclass(frozen=True, slots=True)
class JwtFixture:
    settings: ApiSettings
    signing_key: Ed25519PrivateKey


@dataclass(frozen=True, slots=True)
class JwtTokenSpec:
    roles: tuple[str, ...] = ("approver",)
    issuer: str = "https://issuer.example"
    signing_key: Ed25519PrivateKey | None = None
    expires_in: timedelta = timedelta(minutes=2)
    key_id: str = "approver-key-1"


def jwt_fixture() -> JwtFixture:
    """Create one complete issuer/audience/JWKS fixture."""
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    settings = ApiSettings(
        jwt_issuer="https://issuer.example",
        jwt_audience="telco-twin-api",
        jwt_jwks_json=json.dumps(
            {
                "keys": [
                    {
                        "alg": "EdDSA",
                        "crv": "Ed25519",
                        "kid": "approver-key-1",
                        "kty": "OKP",
                        "use": "sig",
                        "x": base64.urlsafe_b64encode(public).rstrip(b"=").decode(),
                    }
                ]
            }
        ),
    )
    return JwtFixture(settings, key)


def jwt_bearer(fixture: JwtFixture, spec: JwtTokenSpec | None = None) -> str:
    """Sign one test bearer with optional invalid-claim/key overrides."""
    token_spec = spec or JwtTokenSpec()
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "aud": "telco-twin-api",
            "exp": int((now + token_spec.expires_in).timestamp()),
            "iat": int((now - timedelta(seconds=1)).timestamp()),
            "iss": token_spec.issuer,
            "roles": list(token_spec.roles),
            "sub": "synthetic-approver",
        },
        token_spec.signing_key or fixture.signing_key,
        algorithm="EdDSA",
        headers={"kid": token_spec.key_id},
    )
