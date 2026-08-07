"""Sanity-check do estado extraído — a REGRA DE OURO (verificada como necessária).

'JSON válido ≠ JSON correto': todo estado que a visão produz passa por regras de
poker ANTES de chegar ao Copiloto. Se algo é implausível (carta repetida, board >5,
carta inexistente), a visão ABSTÉM em vez de alimentar o Copiloto com lixo — o erro
fica detectável, não silencioso.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..position_rules import position_is_compatible
from .recognize import RecognizedState
from .synth import RANKS, SUITS

_VALID = {r + s for r in RANKS for s in SUITS}
_MAX_PLAYERS = 9
_MAX_CHIPS = 1_000_000_000
_POSITIONS = {"BTN", "SB", "BB", "UTG", "UTG+1", "MP", "LJ", "HJ", "CO"}


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
    elif isinstance(st.pot, bool) or not isinstance(st.pot, int):
        problems.append("pote precisa ser inteiro")
    elif not 0 <= st.pot <= _MAX_CHIPS:
        problems.append(f"pote fora do limite seguro (0 a {_MAX_CHIPS})")

    card_conf = st.card_confidences
    if card_conf and len(card_conf) != len(cards):
        problems.append("vetor de confiança por carta não corresponde às cartas selecionadas")
    critical: list[float] = [st.confidence]
    if card_conf and len(card_conf) == len(cards):
        critical.extend(card_conf)
    if st.pot is not None:
        critical.append(st.pot_confidence if st.pot_confidence is not None else st.confidence)
    for context_confidence in (st.player_count_confidence, st.position_confidence):
        if context_confidence is not None:
            critical.append(context_confidence)
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

    overall_confidence_valid = (
        not isinstance(st.confidence, bool)
        and isinstance(st.confidence, (int, float))
        and math.isfinite(float(st.confidence))
        and 0 <= float(st.confidence) <= 1
    )
    if (
        overall_confidence_valid
        and abstain_below is not None
        and cards
        and st.confidence < abstain_below
    ):
        problems.append(
            f"confiança da leitura ({st.confidence}) abaixo do limiar seguro "
            f"({abstain_below}) — abstenho em vez de decidir sobre leitura incerta"
        )
    elif overall_confidence_valid and st.confidence < min_confidence:
        warnings.append(f"confiança baixa ({st.confidence}) — leitura incerta")
    if st.pot is None:
        warnings.append("não consegui ler o pote")
    if isinstance(st.n_players, bool) or not isinstance(st.n_players, int):
        problems.append("nº de participantes precisa ser inteiro")
    elif st.n_players and not (2 <= st.n_players <= _MAX_PLAYERS):
        problems.append(f"nº de participantes implausível: {st.n_players} (2 a {_MAX_PLAYERS})")
    if not st.n_players:
        warnings.append("não detectei os jogadores — usando o nº informado")
    if not isinstance(st.position, str):
        problems.append("posição detectada precisa ser texto")
    elif st.position and st.position not in _POSITIONS:
        problems.append(f"posição detectada inválida: {st.position!r}")
    if isinstance(st.position, str) and st.position and not st.n_players:
        problems.append("posição detectada sem contagem de jogadores consistente")
    if (
        isinstance(st.position, str)
        and st.position
        and isinstance(st.n_players, int)
        and not isinstance(st.n_players, bool)
        and st.n_players
        and not position_is_compatible(st.position, st.n_players)
    ):
        problems.append(
            f"posição {st.position!r} impossível para mesa com {st.n_players} jogadores"
        )

    for label, value in (
        ("contagem de jogadores", st.player_count_confidence),
        ("posição", st.position_confidence),
    ):
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or not 0 <= float(value) <= 1
        ):
            problems.append(f"confiança de {label} inválida")

    if st.stacks is not None:
        if not isinstance(st.stacks, dict) or len(st.stacks) > _MAX_PLAYERS:
            problems.append("mapa de stacks detectados inválido")
        else:
            invalid_stack = any(
                isinstance(seat, bool)
                or not isinstance(seat, int)
                or not 0 <= seat < _MAX_PLAYERS
                or isinstance(value, bool)
                or not isinstance(value, int)
                or not 0 <= value <= _MAX_CHIPS
                for seat, value in st.stacks.items()
            )
            if invalid_stack:
                problems.append("stack detectado inválido")
    if st.stack_confidences is not None and (
        not isinstance(st.stack_confidences, dict)
        or not isinstance(st.stacks, dict)
        or set(st.stack_confidences) != set(st.stacks)
        or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or not 0 <= float(value) <= 1
            for value in st.stack_confidences.values()
        )
    ):
        problems.append("confianças dos stacks detectados são inválidas")

    return SanityResult(ok=not problems, problems=problems, warnings=warnings)
