"""Schemas Pydantic — o contrato HTTP/JSON (DTOs de entrada e saída)."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ---- entrada (comandos) ----
class BotSpecSchema(BaseModel):
    name: str
    level: str


class CreateTableRequest(BaseModel):
    human_name: str = "VOCE"
    bots: list[BotSpecSchema] = Field(default_factory=list)
    starting_stack: int = 1000
    small_blind: int = 10
    big_blind: int = 20
    rebuy: bool = True  # cash game (mesa sempre cheia); False = torneio (eliminação)
    mode: str = "play"  # "play" (você joga) | "watch" (só bots, você assiste)
    hand_limit: int | None = None  # para após N mãos (None = sem limite)
    seed: int | None = None


class ActionRequest(BaseModel):
    type: str
    amount: int = 0


# ---- saída (estado da mesa) ----
class InsightSchema(BaseModel):
    kind: str
    label: str
    confidence: float
    probs: list[float] | None = None
    fold_to_bet: float | None = None
    bias: float | None = None


class SeatSchema(BaseModel):
    seat: int
    name: str
    kind: str
    stack: int
    current_bet: int
    status: str
    is_button: bool
    is_turn: bool
    cards: list[str] | None
    insight: InsightSchema | None = None


class ActionSchema(BaseModel):
    seat: int
    type: str
    amount: int


class LegalSchema(BaseModel):
    actions: list[str]
    to_call: int
    min_raise_to: int
    max_raise_to: int


class OpponentReadSchema(BaseModel):
    fold_to_bet: float
    aggression: float
    samples: int


class WinProbSchema(BaseModel):
    seat: int
    prob: float


class CouncilEntrySchema(BaseModel):
    level: str
    action: str
    amount: int
    confidence: float | None = None


class HumanAnalysisSchema(BaseModel):
    equity: float
    win_probs: list[WinProbSchema]
    hand_name: str | None
    outs: int
    draws: list[str]
    pot_odds: float
    ev_call: float
    nut: str | None
    texture: str | None
    spr: float | None
    position: str
    council: list[CouncilEntrySchema]
    best_action: str | None
    best_amount: int | None
    confidence: float | None
    your_profile_fold: float
    your_profile_aggr: float
    your_profile_samples: int


class TableStateResponse(BaseModel):
    table_id: str
    hand_number: int
    phase: str
    board: list[str]
    pot: int
    seats: list[SeatSchema]
    legal: LegalSchema | None
    last_actions: list[ActionSchema]
    winners: list[int] | None
    opponent_read: OpponentReadSchema | None = None
    analysis: HumanAnalysisSchema | None = None
