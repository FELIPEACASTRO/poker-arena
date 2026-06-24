"""Camada de aplicação (use cases) — depende só do domínio (engine + bots).

Não conhece HTTP/Pydantic. A API (camada externa) é que adapta isto para a web.
"""

from .bot_factory import (
    LEVELS,
    ExpertUnavailable,
    UnknownBotLevel,
    available_levels,
    create_bot,
    expert_model_path,
)
from .game_session import (
    BotSpec,
    GameSession,
    InvalidActionError,
    SessionConfig,
    build_session,
)
from .session_repository import (
    InMemorySessionRepository,
    SessionNotFound,
    SessionRepository,
)
from .views import (
    ActionView,
    LegalView,
    OpponentReadView,
    SeatView,
    TableStateView,
)

__all__ = [
    "LEVELS",
    "ActionView",
    "ExpertUnavailable",
    "available_levels",
    "expert_model_path",
    "BotSpec",
    "GameSession",
    "InMemorySessionRepository",
    "InvalidActionError",
    "LegalView",
    "OpponentReadView",
    "SeatView",
    "SessionConfig",
    "SessionNotFound",
    "SessionRepository",
    "TableStateView",
    "UnknownBotLevel",
    "build_session",
    "create_bot",
]
