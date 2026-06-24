"""AdaptiveBot — aprende o estilo do humano e o EXPLORA (camada sobre a heurística).

Base: força da mão (treys). Ajuste pelo modelo do oponente:
- humano desiste demais diante de aposta (over-folder) -> infla a força percebida
  -> o bot blefa/pressiona mais (porque ele costuma desistir);
- humano paga tudo (calling station) -> desinfla -> o bot só aposta valor.

É a ideia 'GTO × exploração' viva: o bot ajusta o jogo ao SEU estilo.
"""

from __future__ import annotations

from ..engine.actions import Action
from ._policy import decide_from_equity
from .heuristic_bot import postflop_strength, preflop_strength
from .insight import BotInsight
from .observation import Observation
from .opponent_model import OpponentModel


class AdaptiveBot:
    def __init__(
        self,
        model: OpponentModel,
        name: str = "Adaptativo",
        seed: int | None = None,
        raise_threshold: float = 0.62,
        aggressiveness: float = 0.6,
    ) -> None:
        self.name = name
        self._model = model
        self._raise_threshold = raise_threshold
        self._aggr = aggressiveness
        self._last = (0.0, 0.5, 0.0)  # (efetiva, fold_to_bet, viés)

    def act(self, obs: Observation) -> Action:
        if len(obs.board) >= 3:
            strength = postflop_strength(obs.hole, obs.board)
        else:
            strength = preflop_strength(obs.hole)
        # leitura do oponente -> vies de exploracao (0.5 = neutro)
        bias = (self._model.fold_to_bet - 0.5) * self._aggr
        effective = min(1.0, max(0.0, strength + bias))
        self._last = (effective, self._model.fold_to_bet, bias)
        return decide_from_equity(obs, effective, self._raise_threshold)

    def insight(self) -> BotInsight:
        effective, fold_to_bet, bias = self._last
        if bias > 0.02:
            note = "explora: você desiste muito → pressiona/blefa"
        elif bias < -0.02:
            note = "explora: você paga muito → só aposta valor"
        else:
            note = "ainda lendo seu estilo (neutro)"
        return BotInsight(
            kind="adaptive",
            label=note,
            confidence=effective,
            fold_to_bet=fold_to_bet,
            bias=bias,
        )
