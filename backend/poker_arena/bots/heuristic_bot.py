"""HeuristicBot — nível 🟡 Amador. Decide por força da mão (regras), sem simulação.

Pré-flop: força a partir das duas cartas (par, cartas altas, suited, conectada).
Pós-flop: percentil da melhor mão de 5 cartas (via treys). A força entra na mesma
política de pot odds usada pelo MonteCarloBot.
"""

from __future__ import annotations

from ..engine.actions import Action
from ..engine.cards import Card
from ..engine.evaluator import evaluate
from ._policy import decide_from_equity
from .insight import BotInsight
from .observation import Observation

_TREYS_BEST = 1
_TREYS_WORST = 7462


def preflop_strength(hole: list[Card] | tuple[Card, ...]) -> float:
    r1, r2 = sorted((int(hole[0].rank), int(hole[1].rank)), reverse=True)
    suited = hole[0].suit == hole[1].suit
    pair = r1 == r2
    strength = (r1 + r2) / 28.0  # AA = 28/28
    if pair:
        strength += 0.25
    if suited:
        strength += 0.06
    if not pair and (r1 - r2) == 1:  # conectada
        strength += 0.04
    return min(strength, 1.0)


def postflop_strength(hole: tuple[Card, ...], board: tuple[Card, ...]) -> float:
    score = evaluate(list(hole), list(board))  # treys: menor = melhor
    return 1.0 - (score - _TREYS_BEST) / (_TREYS_WORST - _TREYS_BEST)


class HeuristicBot:
    def __init__(
        self,
        name: str = "HeuristicBot",
        seed: int | None = None,
        raise_threshold: float = 0.72,
    ):
        self.name = name
        self.raise_threshold = raise_threshold
        self.last_strength = 0.0

    def act(self, obs: Observation) -> Action:
        if obs.board:
            strength = postflop_strength(obs.hole, obs.board)
        else:
            strength = preflop_strength(obs.hole)
        self.last_strength = strength
        return decide_from_equity(obs, strength, self.raise_threshold)

    def insight(self) -> BotInsight:
        return BotInsight(
            kind="heuristic",
            label=f"Força da mão {round(self.last_strength * 100)}%",
            confidence=self.last_strength,
        )
