"""Bounded MCP Streamable HTTP session and SSE event store."""

from __future__ import annotations

import re
import secrets
import string
import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, Literal

from telco_twin.mcp.state import McpToolError

if TYPE_CHECKING:
    from telco_twin.mcp.contracts import JsonRpc

VISIBLE_ASCII: Final = string.ascii_letters + string.digits + "-_"
EVENT_ID_PARTS: Final = 3
EVENT_SEQUENCE_RE: Final = re.compile(r"^[1-9][0-9]*$", re.ASCII)
DEFAULT_MAX_RETAINED_STREAMS: Final = 8
DEFAULT_MAX_SESSION_REPLAY_EVENTS: Final = 256


@dataclass(frozen=True, slots=True)
class StreamEvent:
    """One replayable event scoped to a single SSE stream."""

    event_id: str
    payload: JsonRpc
    sequence: int


@dataclass(slots=True)
class McpStream:
    """Replay window for one SSE stream."""

    stream_id: str
    max_events: int
    next_sequence: int = 1
    events: deque[StreamEvent] = field(default_factory=deque)

    def append(self, session_id: str, payload: JsonRpc) -> StreamEvent:
        """Append a replayable event and trim this stream's bounded window."""
        event = StreamEvent(
            event_id=f"{session_id}:{self.stream_id}:{self.next_sequence}",
            payload=payload,
            sequence=self.next_sequence,
        )
        self.next_sequence += 1
        self.events.append(event)
        while len(self.events) > self.max_events:
            _ = self.events.popleft()
        return event

    def contains_cursor(self, sequence: int) -> bool:
        """Return whether a Last-Event-ID cursor still names retained stream history."""
        first = self.events[0].sequence if self.events else self.next_sequence
        return first <= sequence < self.next_sequence


@dataclass(slots=True)
class McpSession:
    """Initialized HTTP MCP session plus owned SSE streams."""

    session_id: str
    expires_at: float
    max_stream_events: int
    max_retained_streams: int = DEFAULT_MAX_RETAINED_STREAMS
    max_session_replay_events: int = DEFAULT_MAX_SESSION_REPLAY_EVENTS
    initialized: bool = False
    next_stream_sequence: int = 1
    streams: dict[str, McpStream] = field(default_factory=dict)

    def open_stream(self) -> list[tuple[str, JsonRpc]]:
        """Create a live SSE stream with bounded replayable server notifications."""
        stream_id = f"s{self.next_stream_sequence}"
        self.next_stream_sequence += 1
        stream = McpStream(stream_id=stream_id, max_events=self.max_stream_events)
        self.streams[stream_id] = stream
        frames = [_frame(stream.append(self.session_id, _server_ping(stream_id, 1)))]
        self._trim_replay_budget()
        return frames

    def append_ping(self, stream_id: str) -> tuple[str, JsonRpc] | None:
        """Append one legitimate MCP ping request to an existing stream."""
        stream = self.streams.get(stream_id)
        if stream is None:
            return None
        event = stream.append(self.session_id, _server_ping(stream_id, stream.next_sequence))
        self._trim_replay_budget()
        return _frame(event)

    def replay(self, last_event_id: str) -> list[tuple[str, JsonRpc]] | None:
        """Replay events after a validated same-session, same-stream cursor."""
        cursor = self._parse_event_id(last_event_id)
        if cursor is None:
            return None
        stream_id, sequence = cursor
        stream = self.streams.get(stream_id)
        if stream is None or not stream.contains_cursor(sequence):
            return None
        return [_frame(event) for event in stream.events if event.sequence > sequence]

    def replay_event_count(self) -> int:
        """Return the aggregate retained replay-event count for this session."""
        return sum(len(stream.events) for stream in self.streams.values())

    def _trim_replay_budget(self) -> None:
        while len(self.streams) > self.max_retained_streams:
            oldest_stream_id = next(iter(self.streams))
            del self.streams[oldest_stream_id]
        while self.replay_event_count() > self.max_session_replay_events and self.streams:
            oldest_stream_id = next(iter(self.streams))
            oldest_stream = self.streams[oldest_stream_id]
            if oldest_stream.events:
                _ = oldest_stream.events.popleft()
            if not oldest_stream.events:
                del self.streams[oldest_stream_id]

    def _parse_event_id(self, event_id: str) -> tuple[str, int] | None:
        parts = event_id.split(":")
        if len(parts) != EVENT_ID_PARTS or parts[0] != self.session_id:
            return None
        if EVENT_SEQUENCE_RE.fullmatch(parts[2]) is None:
            return None
        sequence = int(parts[2])
        return parts[1], sequence


@dataclass(slots=True)
class McpSessionStore:
    """Bounded live-session store with proactive expiry reaping."""

    ttl_seconds: int
    max_sessions: int = 50
    max_stream_events: int = 256
    max_retained_streams: int = DEFAULT_MAX_RETAINED_STREAMS
    max_session_replay_events: int = DEFAULT_MAX_SESSION_REPLAY_EVENTS
    sessions: dict[str, McpSession] = field(default_factory=dict)

    def create(self) -> McpSession:
        """Create a new session after reaping expired entries and enforcing the cap."""
        self.reap_expired()
        if len(self.sessions) >= self.max_sessions:
            code = "session_cap"
            raise McpToolError(code, "too many live MCP sessions")
        session_id = _new_session_id()
        session = McpSession(
            session_id=session_id,
            expires_at=time.monotonic() + self.ttl_seconds,
            max_stream_events=self.max_stream_events,
            max_retained_streams=self.max_retained_streams,
            max_session_replay_events=self.max_session_replay_events,
        )
        self.sessions[session_id] = session
        return session

    def get(self, session_id: str) -> McpSession | None:
        """Return a non-expired session and remove stale entries."""
        self.reap_expired()
        session = self.sessions.get(session_id)
        if session is None:
            return None
        if session.expires_at <= time.monotonic():
            del self.sessions[session_id]
            return None
        return session

    def delete(self, session_id: str) -> bool:
        """Delete one session if present."""
        self.reap_expired()
        return self.sessions.pop(session_id, None) is not None

    def require(
        self,
        headers_map: dict[str, str],
        protocol_version: str,
    ) -> McpSession | Literal[400, 404]:
        """Return the requested live session or an HTTP status failure."""
        if headers_map.get("mcp-protocol-version") != protocol_version:
            return 400
        session_id = headers_map.get("mcp-session-id")
        if session_id is None:
            return 400
        session = self.get(session_id)
        if session is None:
            return 404
        return session

    def clear(self) -> None:
        """Clear all live sessions."""
        self.sessions.clear()

    def reap_expired(self) -> None:
        """Remove all expired sessions before cap-sensitive operations."""
        now = time.monotonic()
        expired = [
            session_id for session_id, session in self.sessions.items() if session.expires_at <= now
        ]
        for session_id in expired:
            del self.sessions[session_id]


def _frame(event: StreamEvent) -> tuple[str, JsonRpc]:
    return event.event_id, event.payload


def _server_ping(stream_id: str, sequence: int) -> JsonRpc:
    return {
        "jsonrpc": "2.0",
        "id": f"ping:{stream_id}:{sequence}",
        "method": "ping",
    }


def _new_session_id() -> str:
    return "".join(secrets.choice(VISIBLE_ASCII) for _ in range(32))
