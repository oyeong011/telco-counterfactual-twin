"""Application runtime binding Task 5 trust, tokens, store, and private sessions."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import assert_never, final

import anyio
from pydantic import ValidationError

from telco_twin.api.abuse import BootstrapRateLimiter
from telco_twin.api.build_identity import build_service_info, repository_root
from telco_twin.api.contracts import DemoSessionResponse
from telco_twin.api.errors import ProblemError
from telco_twin.api.jwt_auth import JwtApprover
from telco_twin.api.runtime_models import ApiSession
from telco_twin.api.scenario_factory import ScenarioFactory
from telco_twin.api.settings import ApiSettings
from telco_twin.approval.authority import (
    SessionIssue,
    load_approval_authority,
)
from telco_twin.approval.state_machine import ApprovalStateMachine
from telco_twin.approval.trust import ApprovalTrustConfig
from telco_twin.domain.approval import RootDescriptor
from telco_twin.state.demo_token import DemoTokenKey
from telco_twin.state.memory_store import DemoSessionStore
from telco_twin.state.store_models import (
    SessionAccess,
    SessionAccessDenied,
    SessionAccessGranted,
    SessionAccessResult,
    SessionCreate,
    SessionCreated,
    SessionCreateDenied,
    SessionSnapshot,
)
from telco_twin.state.trusted_clock import SystemClock, TrustedClock, trusted_timestamp


@dataclass(frozen=True, slots=True)
class AuthorizedSession:
    """Current-epoch authenticated private API session."""

    token: str
    session: ApiSession


def _production_root(settings: ApiSettings) -> RootDescriptor | None:
    encoded = settings.approval_root_descriptor_json
    if encoded is None:
        return None
    try:
        return RootDescriptor.model_validate_json(encoded)
    except ValidationError as error:
        raise ProblemError(
            503,
            "approval_root_invalid",
            "Approval root invalid",
            "The configured production approval root is invalid.",
        ) from error


def _access_problem(result: SessionAccessDenied) -> ProblemError:
    titles = {
        "demo_token_invalid": "Demo token invalid",
        "demo_token_expired": "Demo token expired",
        "demo_session_lost": "Demo session lost",
        "demo_session_not_found": "Demo session not found",
    }
    return ProblemError(
        result.http_status,
        result.code.value,
        titles[result.code.value],
        "The opaque demo-session credential cannot resolve a live session.",
    )


@final
class ApiRuntime:
    """One non-durable process epoch and its application-owned trust facts."""

    def __init__(
        self,
        settings: ApiSettings | None = None,
        clock: TrustedClock | None = None,
    ) -> None:
        """Load trust/configuration and create one bounded process epoch."""
        self.settings = settings or ApiSettings()
        self.clock = clock or SystemClock()
        self.startup_epoch = f"epoch-{secrets.token_hex(12)}"
        descriptor = _production_root(self.settings)
        self.authority = load_approval_authority(self.settings.environment, descriptor)
        root = self.authority.descriptor
        self.trust = ApprovalTrustConfig(
            environment=root.environment,
            root=root,
            trusted_root_hashes=frozenset({root.descriptor_hash}),
        )
        secret = self.settings.demo_token_signing_secret.get_secret_value().encode()
        self.demo_store = DemoSessionStore(
            signing_key=DemoTokenKey(secret),
            startup_epoch=self.startup_epoch,
            clock=self.clock,
        )
        self.scenario_factory = ScenarioFactory(repository_root() / "backend/fixtures/scenarios")
        self.build_info = build_service_info(self.settings, root)
        self.bootstrap_limiter = BootstrapRateLimiter(self.clock)
        self.jwt_approver = JwtApprover.from_settings(self.settings, self.clock)
        self._available = True
        self._sessions_lock = anyio.Lock()
        self._sessions: dict[str, ApiSession] = {}

    @property
    def available(self) -> bool:
        """Return current safe-dependency availability."""
        return self._available

    def set_available(self, available: bool) -> None:
        """Set dependency availability for lifecycle integration and health probes."""
        self._available = available

    async def create_demo_session(self) -> DemoSessionResponse:
        """Create a bounded store slot and retain its private session signer only in memory."""
        if not self._available:
            raise ProblemError(
                503,
                "state_store_unavailable",
                "State unavailable",
                "The live demo store is unavailable.",
            )
        session_id = f"session-{secrets.token_hex(12)}"
        issued_at = trusted_timestamp(self.clock)
        signer = self.authority.issue_session(
            SessionIssue(session_id=session_id, issued_at=issued_at)
        )
        created = await self.demo_store.create_session(
            SessionCreate(session_id=session_id, nonce=secrets.token_bytes(16))
        )
        match created:
            case SessionCreateDenied(code=code):
                raise ProblemError(
                    429,
                    code.value,
                    "Session capacity reached",
                    "The bounded live-session capacity is full.",
                )
            case SessionCreated():
                session = ApiSession(
                    session_id,
                    signer,
                    ApprovalStateMachine(self.trust, self.clock),
                )
            case _:  # pragma: no cover - exhaustive typed union
                assert_never(created)
        async with self._sessions_lock:
            self._sessions[session_id] = session
        return DemoSessionResponse(
            session_id=session_id,
            demo_token=created.token,
            session_certificate=signer.certificate,
            expires_at=created.expires_at,
            startup_epoch=created.startup_epoch,
            durability="process-memory",
            synthetic_only=True,
        )

    async def authorize(self, token: str) -> AuthorizedSession:
        """Resolve Task 5 access semantics before exposing private session state."""
        snapshot = await self.snapshot(token)
        session = self._sessions.get(snapshot.session_id)
        if session is None:
            raise ProblemError(
                503,
                "session_state_unavailable",
                "Session state unavailable",
                "The authenticated session state is unavailable.",
            )
        return AuthorizedSession(token=token, session=session)

    async def snapshot(self, token: str) -> SessionSnapshot:
        """Return one authenticated detached Task 5 snapshot with exact HTTP semantics."""
        if not self._available:
            raise ProblemError(
                503,
                "state_store_unavailable",
                "State unavailable",
                "The live demo store is unavailable.",
            )
        result: SessionAccessResult = await self.demo_store.access(SessionAccess(token=token))
        match result:
            case SessionAccessDenied():
                raise _access_problem(result)
            case SessionAccessGranted(snapshot=snapshot):
                return snapshot
            case _:  # pragma: no cover - exhaustive typed union
                assert_never(result)

    async def find_approval_session(self, request_id: str) -> ApiSession | None:
        """Find one request for an independently authenticated JWT approver."""
        async with self._sessions_lock:
            matches = tuple(
                session
                for session in self._sessions.values()
                if request_id in session.approval_requests
            )
        return matches[0] if len(matches) == 1 else None
