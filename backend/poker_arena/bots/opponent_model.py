"""Modelo do oponente — aprende o estilo do humano observando as jogadas.

Como o servidor é dono do jogo, vemos TUDO (cartas e ações) — sem o problema de
'só ver no showdown' dos datasets externos. Acumulamos os sinais mais EXPLORÁVEIS:
com que frequência o jogador desiste diante de uma aposta (`fold_to_bet`) e o quão
agressivo ele é (`aggression`). O `AdaptiveBot` usa isso pra punir os hábitos.
"""

from __future__ import annotations

from dataclasses import dataclass

_MIN_SAMPLES = 8  # com menos que isso, leitura NEUTRA (0.5) — não chuta com pouca info


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

    def observe(self, action_type: str, *, to_call: int) -> None:
        """Registra uma ação do humano no contexto (havia aposta a pagar?)."""
        if to_call > 0:
            self.faced_bet += 1
            if action_type == "fold":
                self.folded_to_bet += 1
        if action_type == "call":
            self.calls += 1
        elif action_type in ("raise", "all_in"):
            self.raises += 1

    @property
    def samples(self) -> int:
        return self.faced_bet + self.calls + self.raises

    @property
    def fold_to_bet(self) -> float:
        if self.faced_bet < _MIN_SAMPLES:
            return 0.5
        return self.folded_to_bet / self.faced_bet

    @property
    def aggression(self) -> float:
        total = self.calls + self.raises
        if total < _MIN_SAMPLES:
            return 0.5
        return self.raises / total

    def read(self) -> OpponentRead:
        return OpponentRead(
            fold_to_bet=round(self.fold_to_bet, 2),
            aggression=round(self.aggression, 2),
            samples=self.samples,
        )
