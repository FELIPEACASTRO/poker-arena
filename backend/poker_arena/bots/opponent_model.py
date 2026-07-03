"""Modelo do oponente — aprende o estilo do humano observando as jogadas.

Como o servidor é dono do jogo, vemos TUDO (cartas e ações) — sem o problema de
'só ver no showdown' dos datasets externos. Acumulamos os sinais mais EXPLORÁVEIS:
com que frequência o jogador desiste diante de uma aposta (`fold_to_bet`) e o quão
agressivo ele é (`aggression`). O `AdaptiveBot` usa isso pra punir os hábitos.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- PRIORS POPULACIONAIS (dados REAIS, não chute) ---
# Medidos no notebook 07 sobre 250 mil mãos reais de NLHE a dinheiro (Zenodo
# 10796885, CC BY 4.0; medianas de 3.588 jogadores com 50+ mãos). Em vez de
# começar "neutro" (0.5), o modelo começa pelo HUMANO TÍPICO e converge para o
# oponente real conforme observa (suavização bayesiana por pseudo-amostras).
POP_FOLD_TO_BET = 0.70  # mediana real: desiste 70% das vezes diante de aposta
POP_AGGRESSION = 0.46  # mediana real: 46% das ações voluntárias são aumento
_PRIOR_WEIGHT = 8  # o prior "vale" 8 observações; depois os dados reais dominam

_MIN_SAMPLES = 8  # amostra mínima pra leituras SEM prior (ex.: base do tilt)

# --- detector didático de TILT (Palomäki et al., 2014: perder grande derruba a
# regulação emocional e a agressão sobe nas mãos seguintes) ---
_TILT_LOSS_BB = 15.0  # perda >= 15 big blinds numa mão abre a janela de observação
_TILT_WINDOW = 2  # observa as 2 mãos seguintes à perda
_TILT_MIN_ACTIONS = 3  # mínimo de call/raise na janela pra opinar
_TILT_DELTA = 0.25  # aumento de agressão vs a base que caracteriza tilt


@dataclass(frozen=True)
class OpponentRead:
    fold_to_bet: float  # 0..1 (alto = desiste muito -> blefável)
    aggression: float   # 0..1 (alto = agressivo)
    samples: int        # quantas ações já observamos


class OpponentModel:
    def __init__(self) -> None:
        self.faced_bet = 0
        self.folded_to_bet = 0
        self.calls = 0
        self.raises = 0
        # janela de tilt (aberta por uma perda grande; ver constantes acima)
        self._tilt_hands_left = 0
        self._win_calls = 0
        self._win_raises = 0

    def observe(self, action_type: str, *, to_call: int) -> None:
        """Registra uma ação do humano no contexto (havia aposta a pagar?)."""
        if to_call > 0:
            self.faced_bet += 1
            if action_type == "fold":
                self.folded_to_bet += 1
        if action_type == "call":
            self.calls += 1
            if self._tilt_hands_left > 0:
                self._win_calls += 1
        elif action_type in ("raise", "all_in"):
            self.raises += 1
            if self._tilt_hands_left > 0:
                self._win_raises += 1

    def note_hand_result(self, delta_bb: float) -> None:
        """Informa o resultado da mão do humano (em big blinds) ao fim da mão.

        Fecha/abre a janela de tilt: uma perda >= _TILT_LOSS_BB abre uma janela
        fresca de _TILT_WINDOW mãos em que a agressão é comparada com a base.
        """
        if self._tilt_hands_left > 0:
            self._tilt_hands_left -= 1
        if delta_bb <= -_TILT_LOSS_BB:
            self._tilt_hands_left = _TILT_WINDOW
            self._win_calls = 0
            self._win_raises = 0

    @property
    def samples(self) -> int:
        return self.faced_bet + self.calls + self.raises

    @property
    def fold_to_bet(self) -> float:
        """Suavizado pelo prior populacional: começa em 0.70 (humano típico real)
        e converge pro observado conforme a amostra cresce."""
        return (self.folded_to_bet + POP_FOLD_TO_BET * _PRIOR_WEIGHT) / (
            self.faced_bet + _PRIOR_WEIGHT
        )

    @property
    def aggression(self) -> float:
        """Suavizado pelo prior populacional (0.46), mesma lógica bayesiana."""
        total = self.calls + self.raises
        return (self.raises + POP_AGGRESSION * _PRIOR_WEIGHT) / (total + _PRIOR_WEIGHT)

    @property
    def _baseline_aggr(self) -> float | None:
        """Agressão de base SEM o default neutro (None enquanto a amostra é pequena)."""
        total = self.calls + self.raises
        if total < _MIN_SAMPLES:
            return None
        return self.raises / total

    @property
    def tilt_delta(self) -> float:
        """Agressão na janela pós-perda − agressão de base (0.0 quando não avaliável)."""
        base = self._baseline_aggr
        n = self._win_calls + self._win_raises
        if base is None or n < _TILT_MIN_ACTIONS:
            return 0.0
        return self._win_raises / n - base

    @property
    def tilt(self) -> bool:
        """True enquanto, na janela pós-perda, a agressão sobe além do limiar."""
        return self._tilt_hands_left > 0 and self.tilt_delta >= _TILT_DELTA

    def read(self) -> OpponentRead:
        return OpponentRead(
            fold_to_bet=round(self.fold_to_bet, 2),
            aggression=round(self.aggression, 2),
            samples=self.samples,
        )
