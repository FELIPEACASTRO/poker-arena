"""Tipos de ação que um jogador pode tomar numa rodada de aposta."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ActionType(Enum):
    FOLD = "fold"
    CHECK = "check"
    CALL = "call"
    RAISE = "raise"
    ALL_IN = "all_in"


@dataclass(frozen=True)
class Action:
    type: ActionType
    amount: int = 0  # aposta TOTAL nesta rodada (para RAISE/ALL_IN)
