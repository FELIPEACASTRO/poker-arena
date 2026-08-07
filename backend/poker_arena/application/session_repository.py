"""Repositório de sessões (padrão Repository + DIP).

`SessionRepository` é a interface (abstração); `InMemorySessionRepository` é uma
implementação. A API depende da interface, não da implementação — então trocar
por Redis/DB no futuro não afeta o resto (Dependency Inversion).
"""

from __future__ import annotations

import threading
from typing import Protocol

from .game_session import GameSession


class SessionNotFound(KeyError):
    """Sessão inexistente no repositório."""


class SessionRepository(Protocol):
    def add(self, session: GameSession) -> None: ...
    def get(self, session_id: str) -> GameSession: ...
    def remove(self, session_id: str) -> None: ...


class InMemorySessionRepository:
    """Guarda sessões em memória (suficiente para um jogo single-player local)."""

    def __init__(self) -> None:
        self._store: dict[str, GameSession] = {}
        self._lock = threading.RLock()

    def add(self, session: GameSession) -> None:
        with self._lock:
            existing = self._store.get(session.id)
            if existing is session:
                return
            if existing is not None:
                raise ValueError(f"já existe uma sessão com id {session.id!r}")
            self._store[session.id] = session

    def get(self, session_id: str) -> GameSession:
        with self._lock:
            try:
                return self._store[session_id]
            except KeyError:
                raise SessionNotFound(session_id) from None

    def remove(self, session_id: str) -> None:
        with self._lock:
            self._store.pop(session_id, None)
