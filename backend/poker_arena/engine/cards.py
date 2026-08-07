"""Cartas e baralho do poker.

`Card.__str__` é compatível com o formato do `treys` ("As", "Th", "2c"),
o que permite o avaliador converter cartas sem lógica extra.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum, IntEnum


def make_rng(seed: int | None) -> random.Random:
    """RNG do jogo.

    - Em produção (seed=None): `SystemRandom`, que sorteia da ENTROPIA do sistema
      operacional (os.urandom) — aleatoriedade criptográfica, imprevisível.
    - Nos testes (seed definido): `Random(seed)`, reproduzível pra fixar uma mão.
    """
    # Seeded decks exist only for reproducible experiments/tests; live play uses SystemRandom.
    return random.Random(seed) if seed is not None else random.SystemRandom()  # noqa: S311


class Rank(IntEnum):
    TWO = 2
    THREE = 3
    FOUR = 4
    FIVE = 5
    SIX = 6
    SEVEN = 7
    EIGHT = 8
    NINE = 9
    TEN = 10
    JACK = 11
    QUEEN = 12
    KING = 13
    ACE = 14


class Suit(Enum):
    SPADES = "s"
    HEARTS = "h"
    DIAMONDS = "d"
    CLUBS = "c"


_RANK_CHAR = {10: "T", 11: "J", 12: "Q", 13: "K", 14: "A"}


@dataclass(frozen=True)
class Card:
    rank: Rank
    suit: Suit

    def __str__(self) -> str:
        r = _RANK_CHAR.get(int(self.rank), str(int(self.rank)))
        return f"{r}{self.suit.value}"


class Deck:
    """Baralho de 52 cartas com embaralhamento determinístico por seed."""

    def __init__(self, seed: int | None = None):
        self._rng = make_rng(seed)
        self.cards: list[Card] = [Card(r, s) for s in Suit for r in Rank]

    def shuffle(self) -> None:
        self._rng.shuffle(self.cards)

    def deal(self, n: int) -> list[Card]:
        if n < 0:
            raise ValueError("não é possível distribuir quantidade negativa de cartas")
        if n > len(self.cards):
            raise ValueError("não há cartas suficientes no baralho")
        dealt, self.cards = self.cards[:n], self.cards[n:]
        return dealt
