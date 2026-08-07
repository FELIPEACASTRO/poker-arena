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
from .insight import BotInsight
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
    if num_opponents < 1:
        raise ValueError("num_opponents precisa ser positivo")
    if n_samples <= 0:
        raise ValueError("n_samples precisa ser positivo")
    my = [TCard.new(str(c)) for c in hole]
    bd = [TCard.new(str(c)) for c in board]
    known = set(my) | set(bd)
    deck = [c for c in _FULL_DECK if c not in known]
    need_board = 5 - len(bd)
    if need_board < 0 or num_opponents * 2 + need_board > len(deck):
        raise ValueError("cartas/oponentes incompatíveis com um baralho de 52 cartas")

    equity = 0.0
    for _ in range(n_samples):
        rng.shuffle(deck)
        idx = num_opponents * 2
        opps = [deck[i * 2 : i * 2 + 2] for i in range(num_opponents)]
        sim_board = bd + deck[idx : idx + need_board]
        my_score = _EVAL.evaluate(sim_board, my)
        scores = [my_score, *(_EVAL.evaluate(sim_board, o) for o in opps)]
        best = min(scores)
        if my_score == best:  # treys: menor = melhor
            equity += 1.0 / sum(score == best for score in scores)
    return equity / n_samples


class MonteCarloBot:
    def __init__(
        self,
        name: str = "MonteCarloBot",
        seed: int | None = None,
        n_samples: int = 200,
        raise_threshold: float = 0.72,
    ):
        self.name = name
        self.n_samples = n_samples
        self.raise_threshold = raise_threshold
        self._rng = random.Random(seed)  # noqa: S311 - reproducible strategy simulation
        self.last_equity = 0.0

    def act(self, obs: Observation) -> Action:
        n_opp = max(
            sum(1 for p in obs.players if p.status != "folded" and p.seat != obs.seat),
            1,
        )
        equity = estimate_equity(obs.hole, obs.board, n_opp, self.n_samples, self._rng)
        self.last_equity = equity
        return decide_from_equity(obs, equity, self.raise_threshold)

    def insight(self) -> BotInsight:
        return BotInsight(
            kind="montecarlo",
            label=f"Equity {round(self.last_equity * 100)}% ({self.n_samples} simulações)",
            confidence=self.last_equity,
        )
