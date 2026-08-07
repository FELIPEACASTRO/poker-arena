"""BotInsight — o 'porquê' de uma decisão; deixa a IA em caixa de vidro (glass-box).

Cada cérebro expõe o raciocínio REAL que moveu a jogada — nada inventado, é o mesmo
número que decide a ação:
- Expert      -> a distribuição de probabilidade das 5 ações (saída da rede).
- Intermediário (Monte Carlo) -> a equity simulada.
- Amador      -> a força da mão.
- Adaptativo  -> a força efetiva + a leitura do oponente.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BotInsight:
    kind: str  # expert | montecarlo | heuristic | adaptive | random
    label: str  # resumo curto, legível pro humano
    confidence: float  # sinal principal em [0,1] (vira a barra)
    probs: tuple[float, ...] | None = None  # expert: 5 probabilidades (ordem de ACTIONS)
    fold_to_bet: float | None = None  # adaptive: o quanto o humano desiste
    bias: float | None = None  # adaptive: viés de exploração aplicado
