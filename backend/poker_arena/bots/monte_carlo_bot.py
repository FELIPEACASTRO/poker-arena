"""MonteCarloBot — nível 🟠 Intermediário. Estima equity por simulação + pot odds.

Amostra mãos dos oponentes do baralho restante, completa o board, avalia o showdown
e acumula vitórias/empates. A equity resultante entra numa política heurística de
pot odds. É um baseline matemático (sem ML), não uma política GTO comprovada.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from itertools import combinations

from treys import Card as TCard
from treys import Evaluator as TEvaluator

from ..engine.actions import Action
from ..engine.cards import Card
from ._policy import decide_from_equity
from .insight import BotInsight
from .observation import Observation

_EVAL = TEvaluator()
_FULL_DECK = [TCard.new(r + s) for r in "23456789TJQKA" for s in "shdc"]
_Z95 = 1.959963984540054


def bounded_wilson_interval(mean: float, total: int) -> tuple[float, float]:
    """Wilson score interval for a bounded payoff mean, including safe edge bounds.

    Split-pot payoffs can be fractional, so this is an explicit conservative
    Bernoulli-envelope approximation for sampling uncertainty, not an exact CI.
    """

    if total <= 0 or not 0 <= mean <= 1:
        raise ValueError("mean/total inválidos para intervalo de Wilson")
    z2 = _Z95**2
    denominator = 1 + z2 / total
    center = (mean + z2 / (2 * total)) / denominator
    margin = (_Z95 / denominator) * math.sqrt(mean * (1 - mean) / total + z2 / (4 * total**2))
    return max(0.0, center - margin), min(1.0, center + margin)


@dataclass(frozen=True)
class EquityEstimate:
    """Equity plus provenance that distinguishes exact and sampled results."""

    equity: float
    trials: int
    method: str
    standard_error: float
    ci95_lower: float
    ci95_upper: float


def _validate_and_prepare(
    hole: list[Card] | tuple[Card, ...],
    board: list[Card] | tuple[Card, ...],
    num_opponents: int,
) -> tuple[list[int], list[int], list[int], int]:
    if len(hole) != 2:
        raise ValueError("hole precisa conter exatamente duas cartas")
    if len(board) not in (0, 3, 4, 5):
        raise ValueError("board precisa conter 0, 3, 4 ou 5 cartas")
    if num_opponents < 1:
        raise ValueError("num_opponents precisa ser positivo")
    my = [TCard.new(str(card)) for card in hole]
    bd = [TCard.new(str(card)) for card in board]
    if len(set(my + bd)) != len(my) + len(bd):
        raise ValueError("hole e board contêm cartas repetidas")
    known = set(my) | set(bd)
    deck = [card for card in _FULL_DECK if card not in known]
    need_board = 5 - len(bd)
    if num_opponents * 2 + need_board > len(deck):
        raise ValueError("cartas/oponentes incompatíveis com um baralho de 52 cartas")
    return my, bd, deck, need_board


def estimate_equity_with_uncertainty(
    hole: list[Card] | tuple[Card, ...],
    board: list[Card] | tuple[Card, ...],
    num_opponents: int,
    n_samples: int,
    rng: random.Random,
    *,
    exact_when_possible: bool = True,
) -> EquityEstimate:
    """Estimate showdown equity and disclose exactness and sampling error.

    Heads-up river equity is inexpensive enough to enumerate completely. Other
    states use Monte Carlo and expose an approximate 95% confidence interval over
    the split-pot payoff. The interval covers sampling error only; it does not
    cover modelling error from assuming uniform opponent ranges.
    """

    if n_samples <= 0:
        raise ValueError("n_samples precisa ser positivo")
    my, bd, deck, need_board = _validate_and_prepare(hole, board, num_opponents)

    if exact_when_possible and num_opponents == 1 and need_board == 0:
        equity_sum = 0.0
        trials = 0
        my_score = _EVAL.evaluate(bd, my)
        for opponent in combinations(deck, 2):
            opponent_score = _EVAL.evaluate(bd, list(opponent))
            if my_score < opponent_score:
                equity_sum += 1.0
            elif my_score == opponent_score:
                equity_sum += 0.5
            trials += 1
        value = equity_sum / trials
        return EquityEstimate(
            equity=value,
            trials=trials,
            method="exact-river-heads-up",
            standard_error=0.0,
            ci95_lower=value,
            ci95_upper=value,
        )

    need_total = num_opponents * 2 + need_board
    mean = 0.0
    second_moment = 0.0
    for trial in range(1, n_samples + 1):
        drawn = rng.sample(deck, need_total)
        opponent_cards = drawn[: num_opponents * 2]
        opponents = [opponent_cards[index * 2 : index * 2 + 2] for index in range(num_opponents)]
        simulated_board = bd + drawn[num_opponents * 2 :]
        my_score = _EVAL.evaluate(simulated_board, my)
        scores = [my_score, *(_EVAL.evaluate(simulated_board, hand) for hand in opponents)]
        best = min(scores)
        payoff = 0.0
        if my_score == best:  # treys: lower is better
            payoff = 1.0 / sum(score == best for score in scores)
        delta = payoff - mean
        mean += delta / trial
        second_moment += delta * (payoff - mean)

    variance = second_moment / (n_samples - 1) if n_samples > 1 else 0.0
    empirical_standard_error = math.sqrt(max(variance, 0.0) / n_samples)
    ci95_lower, ci95_upper = bounded_wilson_interval(mean, n_samples)
    interval_equivalent_se = (ci95_upper - ci95_lower) / (2 * _Z95)
    standard_error = max(empirical_standard_error, interval_equivalent_se)
    return EquityEstimate(
        equity=mean,
        trials=n_samples,
        method="monte-carlo-uniform-range",
        standard_error=standard_error,
        ci95_lower=ci95_lower,
        ci95_upper=ci95_upper,
    )


def estimate_equity(
    hole: list[Card] | tuple[Card, ...],
    board: list[Card] | tuple[Card, ...],
    num_opponents: int,
    n_samples: int,
    rng: random.Random,
    *,
    exact_when_possible: bool = True,
) -> float:
    """Equity in [0, 1] against uniform unknown opponent ranges."""

    return estimate_equity_with_uncertainty(
        hole,
        board,
        num_opponents,
        n_samples,
        rng,
        exact_when_possible=exact_when_possible,
    ).equity


class MonteCarloBot:
    def __init__(
        self,
        name: str = "MonteCarloBot",
        seed: int | None = None,
        n_samples: int = 1_000,
        raise_threshold: float = 0.72,
    ):
        self.name = name
        self.n_samples = n_samples
        self.raise_threshold = raise_threshold
        self._rng = random.Random(seed)  # noqa: S311 - reproducible strategy simulation
        self.last_equity = 0.0
        self.last_estimate: EquityEstimate | None = None

    def act(self, obs: Observation) -> Action:
        n_opp = max(
            sum(1 for p in obs.players if p.status != "folded" and p.seat != obs.seat),
            1,
        )
        estimate = estimate_equity_with_uncertainty(
            obs.hole, obs.board, n_opp, self.n_samples, self._rng
        )
        self.last_estimate = estimate
        self.last_equity = estimate.equity
        return decide_from_equity(obs, estimate.equity, self.raise_threshold)

    def insight(self) -> BotInsight:
        method = self.last_estimate.method if self.last_estimate else "not-evaluated"
        trials = self.last_estimate.trials if self.last_estimate else 0
        label = (
            f"Equity {round(self.last_equity * 100)}% (exata, {trials} combinações)"
            if method == "exact-river-heads-up"
            else f"Equity {round(self.last_equity * 100)}% ({trials} simulações)"
        )
        return BotInsight(
            kind="montecarlo",
            label=label,
            confidence=self.last_equity,
        )
