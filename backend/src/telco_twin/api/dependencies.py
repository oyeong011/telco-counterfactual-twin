"""Header, origin, and approval authentication boundary helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Final

from fastapi import Header, Request, Response
from pydantic import TypeAdapter, ValidationError

from telco_twin.api.errors import ProblemError
from telco_twin.domain._contract import ContractId

if TYPE_CHECKING:
    from telco_twin.api.runtime import ApiRuntime, AuthorizedSession
    from telco_twin.api.runtime_models import ApiSession

CONTRACT_ID_ADAPTER: Final[TypeAdapter[ContractId]] = TypeAdapter(ContractId)


def require_demo_token(value: str | None) -> str:
    """Require the opaque demo credential without inspecting its content."""
    if value is None or not value:
        raise ProblemError(
            401,
            "demo_token_required",
            "Demo token required",
            "X-Demo-Session-Token is required for this operation.",
        )
    return value


def require_idempotency_key(value: str | None) -> ContractId:
    """Parse a required session-scoped idempotency key."""
    if value is None or not value:
        raise ProblemError(
            400,
            "idempotency_key_required",
            "Idempotency key required",
            "Idempotency-Key is required for this mutation.",
        )
    try:
        return CONTRACT_ID_ADAPTER.validate_python(value)
    except ValidationError as error:
        raise ProblemError(
            400,
            "idempotency_key_invalid",
            "Idempotency key invalid",
            "Idempotency-Key does not match the identifier contract.",
        ) from error


async def authorized_session(runtime: ApiRuntime, token: str | None) -> AuthorizedSession:
    """Authenticate one session through the Task 5 token/store contract."""
    return await runtime.authorize(require_demo_token(token))


async def bootstrap_guard(runtime: ApiRuntime, request: Request) -> None:
    """Enforce exact allowed Origin and per-IP bootstrap abuse limits."""
    origin = request.headers.get("origin")
    if origin is None:
        raise ProblemError(
            403,
            "origin_required",
            "Origin required",
            "Bootstrap requires an allowed Origin header.",
        )
    if origin not in runtime.settings.allowed_origins:
        raise ProblemError(
            403, "origin_forbidden", "Origin forbidden", "The bootstrap Origin is not allowed."
        )
    client_ip = request.client.host if request.client is not None else "unknown-client"
    result = await runtime.bootstrap_limiter.consume(client_ip)
    if not result.accepted:
        raise ProblemError(
            429,
            "bootstrap_rate_limited",
            "Bootstrap rate limited",
            "The per-IP bootstrap allowance is exhausted.",
            headers=(("Retry-After", str(result.retry_after_seconds)),),
        )


@dataclass(frozen=True, slots=True)
class DemoApprovalActor:
    """Demo-token approver retaining the authenticated store session."""

    authorized: AuthorizedSession


@dataclass(frozen=True, slots=True)
class JwtApprovalActor:
    """Independently verified JWT approver bound to the request-owning session."""

    session: ApiSession


type ApprovalActor = DemoApprovalActor | JwtApprovalActor


@dataclass(frozen=True, slots=True)
class ApprovalHeaders:
    """Three approval authorization/idempotency headers parsed by FastAPI."""

    demo_token: str | None
    authorization: str | None
    idempotency: str | None


async def approval_headers(
    demo_token: Annotated[str | None, Header(alias="X-Demo-Session-Token")] = None,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    idempotency: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ApprovalHeaders:
    """Collect approval headers without representing bearer values in logs or errors."""
    return ApprovalHeaders(demo_token, authorization, idempotency)


async def approval_actor(
    runtime: ApiRuntime,
    request_id: str,
    demo_token: str | None,
    authorization: str | None,
) -> ApprovalActor:
    """Resolve demo authority or explicitly reject unavailable non-demo JWT authority."""
    if demo_token is not None:
        return DemoApprovalActor(await runtime.authorize(demo_token))
    if authorization is None:
        raise ProblemError(
            401,
            "approval_auth_required",
            "Approval authentication required",
            "Demo token or configured approver JWT is required.",
        )
    if runtime.jwt_approver is None:
        raise ProblemError(
            503,
            "jwt_approver_disabled",
            "JWT approver disabled",
            "Non-demo approval is disabled without issuer, audience, and JWKS configuration.",
        )
    _ = runtime.jwt_approver.authenticate(authorization)
    session = await runtime.find_approval_session(request_id)
    if session is None:
        raise ProblemError(
            404,
            "approval_request_not_found",
            "Approval request not found",
            "The request does not exist in a live session.",
        )
    return JwtApprovalActor(session)


def mark_replay(response: Response, replayed: bool) -> None:
    """Expose replay as response metadata without changing the response body."""
    response.headers["Idempotency-Replayed"] = "true" if replayed else "false"
