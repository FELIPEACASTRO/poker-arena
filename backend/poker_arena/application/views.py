"""DTOs de saída da aplicação — dataclasses puras (sem framework).

São o contrato que a camada de API traduz para JSON (via ACL/mappers). Manter
isto independente de Pydantic é o que mantém a aplicação desacoplada da web.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InsightView:
    """O raciocínio REAL da última decisão do bot (glass-box)."""

    kind: str
    label: str
    confidence: float
    probs: list[float] | None = None
    fold_to_bet: float | None = None
    bias: float | None = None


@dataclass(frozen=True)
class SeatView:
    seat: int
    name: str
    kind: str  # "human" ou "bot:<level>"
    stack: int
    current_bet: int
    status: str
    is_button: bool
    is_turn: bool
    cards: list[str] | None  # só as do humano, ou reveladas no showdown
    insight: InsightView | None = None  # raciocínio do bot (glass-box), se houver


@dataclass(frozen=True)
class ActionView:
    seat: int
    type: str
    amount: int


@dataclass(frozen=True)
class LegalView:
    actions: list[str]
    to_call: int
    min_raise_to: int
    max_raise_to: int


@dataclass(frozen=True)
class OpponentReadView:
    """O que o bot adaptativo já aprendeu sobre o humano (auto-learning visível)."""

    fold_to_bet: float
    aggression: float
    samples: int


@dataclass(frozen=True)
class TableStateView:
    table_id: str
    hand_number: int
    phase: str  # "human_turn" | "bot_turn" | "hand_over" | "game_over"
    board: list[str]
    pot: int
    seats: list[SeatView]
    legal: LegalView | None
    last_actions: list[ActionView]
    winners: list[int] | None
    opponent_read: OpponentReadView | None = None
