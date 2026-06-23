"""GameSession — orquestra motor + bots (padrão Facade).

Dirige a mão ação a ação: quando é a vez de um bot, ele joga; quando é a vez do
humano, pausa e espera a ação (via `apply_human_action`). Separa comandos
(escrita) de queries (leitura) — CQRS-lite. Depende só do domínio.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from ..bots.base import Bot
from ..bots.observation import observation_for
from ..engine.actions import Action, ActionType
from ..engine.cards import Card
from ..engine.game import Hand
from ..engine.player import Player, PlayerStatus
from ..engine.table import Table
from .bot_factory import create_bot
from .views import ActionView, LegalView, SeatView, TableStateView

_MAX_LOG = 12
_TYPES: dict[str, ActionType] = {
    "fold": ActionType.FOLD,
    "check": ActionType.CHECK,
    "call": ActionType.CALL,
    "raise": ActionType.RAISE,
    "all_in": ActionType.ALL_IN,
}


class InvalidActionError(ValueError):
    """Ação inválida para o estado atual da sessão."""


@dataclass(frozen=True)
class BotSpec:
    name: str
    level: str


@dataclass
class SessionConfig:
    human_name: str = "VOCE"
    bots: list[BotSpec] = field(default_factory=list)
    starting_stack: int = 1000
    small_blind: int = 10
    big_blind: int = 20


def _cards(cards: list[Card]) -> list[str]:
    return [str(c) for c in cards]


class GameSession:
    def __init__(
        self,
        session_id: str,
        table: Table,
        human: Player,
        bot_by_player: dict[int, Bot],
        level_by_player: dict[int, str],
    ) -> None:
        self.id = session_id
        self._table = table
        self._human = human
        self._bot_by_player = bot_by_player
        self._level_by_player = level_by_player
        self._hand: Hand = table.start_hand()
        self._last: list[ActionView] = []
        self._winners: list[int] | None = None
        self._phase = "human_turn"
        self._drive()

    # ---------- comandos (CQRS: escrita) ----------
    def apply_human_action(self, action_type: str, amount: int = 0) -> None:
        if self._phase != "human_turn":
            raise InvalidActionError("não é a vez do humano")
        at = _TYPES.get(action_type)
        if at is None:
            raise InvalidActionError(f"ação desconhecida: {action_type!r}")
        action = Action(at, amount=amount)
        self._record(self._hand.to_act, action)
        self._hand.apply(action)  # o motor valida a legalidade
        self._drive()

    def next_hand(self) -> None:
        if self._phase != "hand_over":
            raise InvalidActionError("a mão atual ainda não terminou")
        self._hand = self._table.start_hand()
        self._last = []
        self._winners = None
        self._phase = "human_turn"
        self._drive()

    # ---------- queries (CQRS: leitura) ----------
    def view(self) -> TableStateView:
        hand = self._hand
        return TableStateView(
            table_id=self.id,
            hand_number=self._table.hand_count + 1,
            phase=self._phase,
            board=_cards(hand.board),
            pot=hand.pot,
            seats=self._seats(),
            legal=self._legal() if self._phase == "human_turn" else None,
            last_actions=list(self._last),
            winners=self._winners,
        )

    def total_chips(self) -> int:
        """Invariante de conservação (todas as fichas, inclusive no pote)."""
        in_pot = self._hand.pot if self._phase == "human_turn" else 0
        return sum(p.stack for p in self._table.players) + in_pot

    # ---------- orquestração interna ----------
    def _drive(self) -> None:
        hand = self._hand
        while True:
            while not hand.round_complete():
                seat = hand.to_act
                player = hand.players[seat]
                if player is self._human:
                    self._phase = "human_turn"
                    return
                action = self._bot_by_player[id(player)].act(observation_for(hand))
                self._record(seat, action)
                hand.apply(action)
            contesting = [p for p in hand.players if p.status != PlayerStatus.FOLDED]
            if len(contesting) <= 1 or len(hand.board) >= 5:
                self._finish_hand()
                return
            hand.advance_street()

    def _finish_hand(self) -> None:
        winners = self._hand.resolve()
        self._winners = [self._hand.players.index(w) for w in winners]
        self._table.end_hand()
        over = self._table.is_over() or self._human.stack <= 0
        self._phase = "game_over" if over else "hand_over"

    def _record(self, seat: int, action: Action) -> None:
        self._last.append(
            ActionView(seat=seat, type=action.type.value, amount=action.amount)
        )
        self._last = self._last[-_MAX_LOG:]

    def _legal(self) -> LegalView:
        hand = self._hand
        me = hand.players[hand.to_act]
        return LegalView(
            actions=sorted(a.value for a in hand.legal_actions()),
            to_call=hand.amount_to_call(),
            min_raise_to=hand.min_raise_to(),
            max_raise_to=me.current_bet + me.stack,
        )

    def _seats(self) -> list[SeatView]:
        hand = self._hand
        reveal = self._phase in ("hand_over", "game_over")
        seats: list[SeatView] = []
        for i, p in enumerate(hand.players):
            is_human = p is self._human
            show = is_human or (reveal and p.status != PlayerStatus.FOLDED)
            kind = "human" if is_human else "bot:" + self._level_by_player[id(p)]
            seats.append(
                SeatView(
                    seat=i,
                    name=p.name,
                    kind=kind,
                    stack=p.stack,
                    current_bet=p.current_bet,
                    status=p.status.value,
                    is_button=(i == hand.button),
                    is_turn=(self._phase == "human_turn" and i == hand.to_act),
                    cards=_cards(p.hole) if (show and p.hole) else None,
                )
            )
        return seats


def build_session(
    config: SessionConfig,
    *,
    session_id: str | None = None,
    seed: int | None = None,
) -> GameSession:
    """Monta jogadores, bots, mesa e a sessão (composição da aplicação)."""
    sid = session_id or uuid.uuid4().hex[:8]
    players = [Player(config.human_name, config.starting_stack)]
    bot_by_player: dict[int, Bot] = {}
    level_by_player: dict[int, str] = {}
    for i, spec in enumerate(config.bots):
        p = Player(spec.name, config.starting_stack)
        players.append(p)
        bot_seed = None if seed is None else seed + i + 1
        bot_by_player[id(p)] = create_bot(spec.level, seed=bot_seed)
        level_by_player[id(p)] = spec.level
    table = Table(players, config.small_blind, config.big_blind, seed=seed)
    return GameSession(sid, table, players[0], bot_by_player, level_by_player)
