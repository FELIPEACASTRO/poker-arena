"""MonteCarloBot — nível 🟠 Intermediário. Estima equity por simulação + pot odds.

Amostra mãos dos oponentes do baralho restante, completa o board, avalia o showdown
e acumula vitórias/empates. A equity resultante entra na política de pot odds. É
matemática pura (sem ML), mas já joga consideravelmente bem.
"""

from __future__ import annotations

import random

from treys import Card as TCard
from treys import Evaluator as TEvaluator

from ..engine.actions import Action
from ..engine.cards import Card
from ._policy import decide_from_equity
from .observation import Observation

_EVAL = TEvaluator()
_FULL_DECK = [TCard.new(r + s) for r in "23456789TJQKA" for s in "shdc"]


def estimate_equity(
    hole: list[Card] | tuple[Card, ...],
    board: list[Card] | tuple[Card, ...],
    num_opponents: int,
    n_samples: int,
    rng: random.Random,
) -> float:
    """Equity em [0, 1] da nossa mão contra `num_opponents` aleatórios."""
    my = [TCard.new(str(c)) for c in hole]
    bd = [TCard.new(str(c)) for c in board]
    known = set(my) | set(bd)
    deck = [c for c in _FULL_DECK if c not in known]
    need_board = 5 - len(bd)

    wins = ties = 0
    for _ in range(n_samples):
        rng.shuffle(deck)
        idx = num_opponents * 2
        opps = [deck[i * 2 : i * 2 + 2] for i in range(num_opponents)]
        sim_board = bd + deck[idx : idx + need_board]
        my_score = _EVAL.evaluate(sim_board, my)
        best_opp = min(_EVAL.evaluate(sim_board, o) for o in opps)
        if my_score < best_opp:  # treys: menor = melhor
            wins += 1
        elif my_score == best_opp:
            ties += 1
    return (wins + ties / 2) / n_samples


class MonteCarloBot:
    def __init__(
        self, name: str = "MonteCarloBot", seed: int | None = None,
        n_samples: int = 200, raise_threshold: float = 0.72,
    ):
        self.name = name
        self.n_samples = n_samples
        self.raise_threshold = raise_threshold
        self._rng = random.Random(seed)
        self.last_equity = 0.0

    def act(self, obs: Observation) -> Action:
        n_opp = max(
            sum(
                1
                for p in obs.players
                if p.status == "active" and p.seat != obs.seat
            ),
            1,
        )
        equity = estimate_equity(
            obs.hole, obs.board, n_opp, self.n_samples, self._rng
        )
        self.last_equity = equity
        return decide_from_equity(obs, equity, self.raise_threshold)
