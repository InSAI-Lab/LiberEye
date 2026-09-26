"""Bounded, process-local EPMC sessions for a single-worker research service."""
from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator

from fastapi import HTTPException

from .epmc import EPMCCoordinator


@dataclass
class Session:
    coordinator: EPMCCoordinator = field(default_factory=EPMCCoordinator)
    lock: threading.RLock = field(default_factory=threading.RLock)
    last_used: float = field(default_factory=time.monotonic)
    active: int = 0


class SessionStore:
    def __init__(self, capacity: int = 256, ttl_s: float = 900) -> None:
        if capacity < 1 or ttl_s <= 0:
            raise ValueError("Session capacity and TTL must be positive")
        self.capacity = capacity
        self.ttl_s = ttl_s
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    @contextmanager
    def use(self, session_id: str | None) -> Iterator[EPMCCoordinator]:
        # Missing IDs are deliberately stateless, never a shared anonymous user.
        if session_id is None:
            yield EPMCCoordinator()
            return
        with self._lock:
            now = time.monotonic()
            for key, session in list(self._sessions.items()):
                if session.active == 0 and now - session.last_used > self.ttl_s:
                    del self._sessions[key]
            if session_id not in self._sessions:
                if len(self._sessions) >= self.capacity:
                    raise HTTPException(503, "Session capacity reached; retry later")
                self._sessions[session_id] = Session()
            session = self._sessions[session_id]
            session.active += 1
        try:
            with session.lock:
                yield session.coordinator
        finally:
            with self._lock:
                session.active -= 1
                session.last_used = time.monotonic()


sessions = SessionStore(
    capacity=int(os.getenv("LIBEREYE_MAX_SESSIONS", "256")),
    ttl_s=float(os.getenv("LIBEREYE_SESSION_TTL_S", "900")),
)
