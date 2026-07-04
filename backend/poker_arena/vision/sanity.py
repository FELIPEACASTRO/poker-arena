"""Sanity-check do estado extraído — a REGRA DE OURO (verificada como necessária).

'JSON válido ≠ JSON correto': todo estado que a visão produz passa por regras de
poker ANTES de chegar ao Copiloto. Se algo é implausível (carta repetida, board >5,
carta inexistente), a visão ABSTÉM em vez de alimentar o Copiloto com lixo — o erro
fica detectável, não silencioso.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .recognize import RecognizedState
from .synth import RANKS, SUITS

_VALID = {r + s for r in RANKS for s in SUITS}


@dataclass
class SanityResult:
    ok: bool
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def check_state(st: RecognizedState, *, min_confidence: float = 0.35) -> SanityResult:
    """Valida o estado reconhecido contra as regras do poker. ok=False => abster."""
    problems: list[str] = []
    warnings: list[str] = []
    cards = list(st.hole) + list(st.board)

    for c in cards:
        if c not in _VALID:
            problems.append(f"carta inexistente detectada: {c!r}")
    if len(set(cards)) != len(cards):
        problems.append("carta repetida entre mão/board (impossível no baralho)")
    if len(st.hole) != 2:
        problems.append(f"esperava 2 cartas suas, detectou {len(st.hole)}")
    if len(st.board) not in (0, 3, 4, 5):
        problems.append(f"board com {len(st.board)} cartas (só 0/3/4/5 é legal)")
    if st.pot is not None and st.pot < 0:
        problems.append("pote negativo")

    if st.confidence < min_confidence:
        warnings.append(f"confiança baixa ({st.confidence}) — leitura incerta")
    if st.pot is None:
        warnings.append("não consegui ler o pote")
    if st.n_players and not (2 <= st.n_players <= 10):
        problems.append(f"nº de participantes implausível: {st.n_players} (2 a 10)")
    if not st.n_players:
        warnings.append("não detectei os jogadores — usando o nº informado")

    return SanityResult(ok=not problems, problems=problems, warnings=warnings)
