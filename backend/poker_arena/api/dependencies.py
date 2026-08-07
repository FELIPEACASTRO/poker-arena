"""Injeção de dependência (DIP). O repositório é um Singleton via `lru_cache` —
a forma testável do padrão (sobreponível com `app.dependency_overrides`), e não o
anti-pattern de variável global mutável.
"""

from __future__ import annotations

from functools import lru_cache

from ..application import InMemorySessionRepository
from ..application.session_repository import SessionRepository


@lru_cache
def get_repository() -> SessionRepository:
    return InMemorySessionRepository()
