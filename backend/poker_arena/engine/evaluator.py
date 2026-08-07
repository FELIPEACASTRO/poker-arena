"""Avaliação de mãos via `treys`.

Encapsula a biblioteca para que o resto do código nunca fale com `treys`
diretamente. Convenção do treys: **menor score = mão melhor** (1 = royal flush).
"""

from __future__ import annotations

from treys import Card as TCard
from treys import Evaluator as TEvaluator

from .cards import Card, Rank, Suit

_EVAL = TEvaluator()
_RANK_FROM_CHAR = {"T": 10, "J": 11, "Q": 12, "K": 13, "A": 14}


def card_from_str(s: str) -> Card:
    """Converte uma string no formato treys ('As', 'Th', '2c') em `Card`."""
    rank_char, suit_char = s[0], s[1]
    rank_val = _RANK_FROM_CHAR.get(rank_char)
    if rank_val is None:
        rank_val = int(rank_char)
    return Card(Rank(rank_val), Suit(suit_char))


def _t(card: Card) -> int:
    return TCard.new(str(card))


def evaluate(hole: list[Card], board: list[Card]) -> int:
    """Score treys (MENOR = melhor). Requer 5 cartas comunitárias."""
    return _EVAL.evaluate([_t(c) for c in board], [_t(c) for c in hole])


def compare(hole_a: list[Card], hole_b: list[Card], board: list[Card]) -> int:
    """+1 se A vence, -1 se B vence, 0 empate."""
    sa, sb = evaluate(hole_a, board), evaluate(hole_b, board)
    return (sb > sa) - (sa > sb)  # menor score vence
