"""Fixed C1 in-process demo-state limits."""

from typing import Final

MAX_LIVE_SESSIONS: Final = 50
MAX_EVENTS_PER_SESSION: Final = 256
SESSION_TTL_SECONDS: Final = 15 * 60
