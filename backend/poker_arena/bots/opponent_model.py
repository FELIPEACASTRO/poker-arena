"""Modelo do oponente — aprende o estilo do humano observando as jogadas.

Como o servidor é dono do jogo, vemos TUDO (cartas e ações) — sem o problema de
'só ver no showdown' dos datasets externos. Acumulamos os sinais mais EXPLORÁVEIS:
com que frequência o jogador desiste diante de uma aposta (`fold_to_bet`) e o quão
agressivo ele é (`aggression`). O `AdaptiveBot` usa isso pra punir os hábitos.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- PRIOR CONSERVADOR ---
# A versão anterior usava números extraídos por um pipeline que amostrava apenas
# a primeira fonte/limite disponível e contava checks como ações voluntárias.
# Esses números não têm representatividade demonstrada e, por isso, não podem
# enviesar decisões de produção. Beta(1, 1) é um prior uniforme, explícito e
# fraco: média 0,5 com apenas duas pseudo-observações. O notebook 07 agora gera
# candidatos auditáveis, mas eles só poderão substituir este default depois de
# validação externa, manifesto de proveniência e gate estatístico pré-registrado.
NEUTRAL_FOLD_TO_BET = 0.5
NEUTRAL_AGGRESSION = 0.5
_PRIOR_WEIGHT = 2

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
    aggression: float  # 0..1 (alto = agressivo)
    samples: int  # quantas ações já observamos


class OpponentModel:
    def __init__(self) -> None:
        self.faced_bet = 0
        self.folded_to_bet = 0
        self.calls = 0
        self.raises = 0
        self._actions = 0
        # janela de tilt (aberta por uma perda grande; ver constantes acima)
        self._tilt_hands_left = 0
        self._win_calls = 0
        self._win_raises = 0
        self._tilt_baseline: float | None = None

    def observe(
        self,
        action_type: str,
        *,
        to_call: int,
        aggressive: bool | None = None,
    ) -> None:
        """Registra uma ação do humano no contexto (havia aposta a pagar?)."""
        self._actions += 1
        if to_call > 0:
            self.faced_bet += 1
            if action_type == "fold":
                self.folded_to_bet += 1
        is_all_in_call = action_type == "all_in" and aggressive is False
        if action_type == "call" or is_all_in_call:
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
            if self._tilt_hands_left == 0:
                self._tilt_baseline = None
        if delta_bb <= -_TILT_LOSS_BB:
            self._tilt_baseline = self._baseline_aggr
            self._tilt_hands_left = _TILT_WINDOW
            self._win_calls = 0
            self._win_raises = 0

    @property
    def samples(self) -> int:
        return self._actions

    @property
    def fold_to_bet(self) -> float:
        """Estimativa suavizada por prior neutro; converge para o observado."""
        return (self.folded_to_bet + NEUTRAL_FOLD_TO_BET * _PRIOR_WEIGHT) / (
            self.faced_bet + _PRIOR_WEIGHT
        )

    @property
    def aggression(self) -> float:
        """Fração raise/(call+raise), suavizada por prior neutro e fraco."""
        total = self.calls + self.raises
        return (self.raises + NEUTRAL_AGGRESSION * _PRIOR_WEIGHT) / (total + _PRIOR_WEIGHT)

    @property
    def read_confidence(self) -> float:
        """Confiança na leitura (0 sem observações, 1 com amostra plena).

        A EXPLORAÇÃO do AdaptiveBot é escalada por isto: sem evidência sobre ESTE
        oponente (ex.: Modo Laboratório, sem humano → faced_bet=0), a confiança é 0
        e não há viés de agressão — o bot joga a força pura da mão, sem virar maníaco.
        O prior neutro segue valendo como ESTIMATIVA/display, não como gatilho de
        agressão sem lastro.
        """
        return min(1.0, self.faced_bet / _MIN_SAMPLES)

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
        base = self._tilt_baseline
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
