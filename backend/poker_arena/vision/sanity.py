"""Sanity-check do estado extraído — a REGRA DE OURO (verificada como necessária).

'JSON válido ≠ JSON correto': todo estado que a visão produz passa por regras de
poker ANTES de chegar ao Copiloto. Se algo é implausível (carta repetida, board >5,
carta inexistente), a visão ABSTÉM em vez de alimentar o Copiloto com lixo — o erro
fica detectável, não silencioso.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .recognize import RecognizedState
from .synth import RANKS, SUITS

_VALID = {r + s for r in RANKS for s in SUITS}
_MAX_PLAYERS = 9


@dataclass
class SanityResult:
    ok: bool
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def check_state(
    st: RecognizedState, *, min_confidence: float = 0.85, abstain_below: float | None = None
) -> SanityResult:
    """Valida o estado reconhecido contra as regras do poker. ok=False => abster.

    `abstain_below`: limiar de abstinência. Quando definido, uma leitura de cartas com
    confiança abaixo desse limiar vira PROBLEMA (abstém) em vez de aviso — o copiloto
    não decide sobre uma leitura abaixo do limiar. Isso reduz risco, sem garantir acurácia."""
    problems: list[str] = []
    warnings: list[str] = []
    cards = list(st.hole) + list(st.board)

    if st.n_cards and st.n_cards != len(cards):
        problems.append(
            f"contador de cartas inconsistente: n_cards={st.n_cards}, estado={len(cards)}"
        )

    for c in cards:
        if c not in _VALID:
            problems.append(f"carta inexistente detectada: {c!r}")
    if len(set(cards)) != len(cards):
        problems.append("carta repetida entre mão/board (impossível no baralho)")
    if len(st.hole) != 2:
        problems.append(f"esperava 2 cartas suas, detectou {len(st.hole)}")
    if len(st.board) not in (0, 3, 4, 5):
        problems.append(f"board com {len(st.board)} cartas (só 0/3/4/5 é legal)")
    if st.pot is None:
        problems.append("não consegui ler o pote com segurança")
    elif isinstance(st.pot, bool) or not isinstance(st.pot, (int, float)):
        problems.append("pote não numérico")
    elif not math.isfinite(float(st.pot)) or st.pot < 0:
        problems.append("pote negativo ou não finito")

    card_conf = st.card_confidences
    if card_conf and len(card_conf) != len(cards):
        problems.append("vetor de confiança por carta não corresponde às cartas selecionadas")
    critical: list[float] = []
    if card_conf and len(card_conf) == len(cards):
        critical.extend(card_conf)
    elif cards:
        critical.append(st.confidence)
    if st.pot is not None:
        critical.append(st.pot_confidence if st.pot_confidence is not None else st.confidence)
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0.0 <= float(value) <= 1.0
        for value in critical
    ):
        problems.append("confiança crítica inválida (esperado valor finito entre 0 e 1)")
    elif critical:
        threshold = max(min_confidence, abstain_below or 0.0)
        weakest = min(float(value) for value in critical)
        if weakest < threshold:
            problems.append(
                f"confiança crítica ({weakest:.3f}) abaixo do limiar seguro ({threshold:.3f})"
            )

    if abstain_below is not None and cards and st.confidence < abstain_below:
        problems.append(
            f"confiança da leitura ({st.confidence}) abaixo do limiar seguro "
            f"({abstain_below}) — abstenho em vez de decidir sobre leitura incerta"
        )
    elif st.confidence < min_confidence:
        warnings.append(f"confiança baixa ({st.confidence}) — leitura incerta")
    if st.pot is None:
        warnings.append("não consegui ler o pote")
    if st.n_players and not (2 <= st.n_players <= _MAX_PLAYERS):
        problems.append(
            f"nº de participantes implausível: {st.n_players} (2 a {_MAX_PLAYERS})"
        )
    if not st.n_players:
        warnings.append("não detectei os jogadores — usando o nº informado")

    if st.stacks is not None:
        invalid_stack = any(
            isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in st.stacks.values()
        )
        if invalid_stack:
            problems.append("stack detectado inválido")

    return SanityResult(ok=not problems, problems=problems, warnings=warnings)
