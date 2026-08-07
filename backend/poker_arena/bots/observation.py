"""Observação filtrada por assento — a ÚNICA visão que um bot recebe.

Segurança por construção: `PublicPlayer` simplesmente não tem campo de cartas, então
é impossível um bot enxergar as hole cards de outro jogador. O motor é a fonte da
verdade; o bot só vê o que esta estrutura expõe.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..engine.actions import Action, ActionType
from ..engine.cards import Card
from ..engine.game import Hand
from ..engine.player import PlayerStatus

if TYPE_CHECKING:
    from .base import Bot


@dataclass(frozen=True)
class PublicPlayer:
    """Estado público de um jogador — SEM cartas privadas, de propósito."""

    seat: int
    name: str
    stack: int
    current_bet: int
    total_committed: int
    status: str
    is_button: bool


@dataclass(frozen=True)
class Observation:
    """Tudo (e só) o que o bot da vez pode ver para decidir."""

    seat: int
    hole: tuple[Card, ...]  # as próprias cartas, e apenas elas
    board: tuple[Card, ...]
    pot: int
    to_call: int
    current_bet: int
    min_raise_to: int
    legal_actions: frozenset[ActionType]
    players: tuple[PublicPlayer, ...]  # estado público de todos (sem hole)
    num_active: int


def observation_for(hand: Hand) -> Observation:
    """Monta a observação do jogador da vez (`hand.to_act`)."""
    seat = hand.to_act
    me = hand.players[seat]
    players = tuple(
        PublicPlayer(
            seat=i,
            name=p.name,
            stack=p.stack,
            current_bet=p.current_bet,
            total_committed=p.total_committed,
            status=p.status.value,
            is_button=(i == hand.button),
        )
        for i, p in enumerate(hand.players)
    )
    return Observation(
        seat=seat,
        hole=tuple(me.hole),
        board=tuple(hand.board),
        pot=hand.pot,
        to_call=hand.amount_to_call(),
        current_bet=hand.current_bet,
        min_raise_to=hand.min_raise_to(),
        legal_actions=frozenset(hand.legal_actions()),
        players=players,
        num_active=sum(1 for p in hand.players if p.status != PlayerStatus.FOLDED),
    )


def as_strategy(bot: Bot) -> Callable[[Hand], Action]:
    """Adapta um `Bot` para a assinatura `strategy(hand) -> Action` do `play_out`."""

    def strategy(hand: Hand) -> Action:
        return bot.act(observation_for(hand))

    return strategy
