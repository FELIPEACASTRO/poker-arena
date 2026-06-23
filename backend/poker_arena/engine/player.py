"""Estado de um jogador na mão (stack, cartas, aposta corrente, status)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .cards import Card


class PlayerStatus(Enum):
    ACTIVE = "active"
    FOLDED = "folded"
    ALL_IN = "all_in"


@dataclass
class Player:
    name: str
    stack: int
    hole: list[Card] = field(default_factory=list)
    status: PlayerStatus = PlayerStatus.ACTIVE
    current_bet: int = 0  # apostado nesta rodada (zera a cada street)
    total_committed: int = 0  # apostado na mão inteira (p/ side pots)
    acted: bool = False  # já agiu nesta rodada?

    def bet(self, amount: int) -> int:
        """Aposta `amount`, limitado ao stack. Retorna o valor efetivamente pago."""
        amount = min(amount, self.stack)
        self.stack -= amount
        self.current_bet += amount
        self.total_committed += amount
        if self.stack == 0:
            self.status = PlayerStatus.ALL_IN
        return amount

    def fold(self) -> None:
        self.status = PlayerStatus.FOLDED

    def reset_for_new_round(self) -> None:
        """Prepara o jogador para a próxima street (não zera total_committed)."""
        self.current_bet = 0
        self.acted = False
