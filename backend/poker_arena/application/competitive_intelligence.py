"""Inteligência competitiva descritiva e auditável para a sessão local.

O módulo não escolhe ações e não altera políticas dos bots. Ele transforma contagens
de oportunidades/eventos do ``WatchStats`` em estimativas explicitamente incertas:

* média posterior Beta(1, 1), para evitar extremos artificiais em amostras pequenas;
* intervalo de Wilson de 95% para comunicar a precisão da frequência observada;
* abstenção até a quantidade mínima de oportunidades;
* sinal de recência EWMA, rotulado como heurístico e nunca como detector causal.

Separar descrição de decisão é deliberado: os trabalhos de opponent modelling mostram
que best responses a modelos imprecisos podem aumentar a própria explorabilidade.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

PROFILE_VERSION = "ci-local-v1"
PRIOR_ALPHA = 1.0
PRIOR_BETA = 1.0
MIN_OPPORTUNITIES = 12
STABLE_OPPORTUNITIES = 30
EWMA_ALPHA = 0.20
RECENCY_DELTA = 0.20
_Z95 = 1.959963984540054


@dataclass(frozen=True)
class TendencyEstimate:
    key: str
    label: str
    family: str
    context: str
    successes: int
    opportunities: int
    observed_rate: float | None
    posterior_mean: float
    interval95_low: float | None
    interval95_high: float | None
    evidence_fraction: float
    evidence: str
    ready: bool


@dataclass(frozen=True)
class RecencyEstimate:
    actions: int
    ewma_aggression: float | None
    long_run_aggression: float | None
    delta: float | None
    direction: str
    ready: bool


@dataclass(frozen=True)
class CompetitiveProfile:
    version: str
    scope: str
    authority: str
    posterior_method: str
    interval_method: str
    minimum_opportunities: int
    signals: list[TendencyEstimate]
    recency: RecencyEstimate


_METRIC_META: dict[str, tuple[str, str, str]] = {
    "vpip": ("Entrada voluntária", "global", "todas as mãos"),
    "pfr": ("Aumento pré-flop", "global", "todas as mãos"),
    "preflop_open_raise": ("Open-raise/RFI", "papel", "pote ainda não aberto"),
    "preflop_three_bet": ("3-bet", "papel", "diante de um primeiro raise"),
    "preflop_fold_to_raise": ("Fold diante de raise", "resposta", "pré-flop"),
    "blind_defense": ("Defesa dos blinds", "papel", "blind diante de raise"),
    "postflop_fold_to_bet": ("Fold diante de aposta", "resposta", "pós-flop"),
    "postflop_aggression_ip": ("Agressão em posição", "ordem", "pós-flop IP"),
    "postflop_aggression_oop": ("Agressão fora de posição", "ordem", "pós-flop OOP"),
    "preflop_limp": ("Open-limp", "papel", "pote ainda não aberto"),
    "preflop_isolation_raise": ("Raise de isolamento", "papel", "diante de limp(s)"),
    "preflop_call_vs_raise": ("Call diante de raise", "resposta", "primeira decisão pré-flop"),
    "preflop_squeeze": ("Squeeze", "papel", "raise seguido de caller"),
    "preflop_four_bet": ("4-bet", "papel", "diante de 3-bet"),
    "late_position_steal": ("Tentativa de roubo", "posição", "CO/BTN/SB em pote fechado"),
    "blind_fold_to_steal": ("Fold do blind a roubo", "resposta", "SB/BB diante de CO/BTN/SB"),
    "blind_vs_blind_sb_open": ("Abertura SB vs BB", "papel", "SB em pote fechado"),
    "blind_vs_blind_bb_defense": ("Defesa BB vs SB", "papel", "BB diante de abertura do SB"),
}

EXACT_POSITIONS = ("UTG", "UTG+1", "MP", "LJ", "HJ", "CO", "BTN", "SB", "BB")

_POSITION_LABELS = {
    "early": "cedo",
    "middle": "meio",
    "late": "tarde",
    "blinds": "blinds",
}


def new_context_counts() -> dict[str, list[int]]:
    """Return mutable ``[opportunities, successes]`` counters for one player."""
    return {key: [0, 0] for key in _METRIC_META if key not in {"vpip", "pfr"}}


def record_context(counts: dict[str, list[int]], key: str, success: bool) -> None:
    """Record exactly one eligible opportunity, failing on unknown/corrupt counters."""
    if key not in counts or len(counts[key]) != 2:
        raise ValueError(f"métrica contextual desconhecida ou corrompida: {key}")
    counts[key][0] += 1
    counts[key][1] += int(success)


def update_ewma(previous: float | None, aggressive: bool) -> float:
    value = float(aggressive)
    return value if previous is None else EWMA_ALPHA * value + (1.0 - EWMA_ALPHA) * previous


def _wilson95(successes: int, opportunities: int) -> tuple[float | None, float | None]:
    if opportunities == 0:
        return None, None
    observed = successes / opportunities
    z2 = _Z95 * _Z95
    denominator = 1.0 + z2 / opportunities
    center = (observed + z2 / (2.0 * opportunities)) / denominator
    margin = (
        _Z95
        * math.sqrt(
            observed * (1.0 - observed) / opportunities + z2 / (4.0 * opportunities * opportunities)
        )
        / denominator
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def estimate(
    key: str,
    successes: int,
    opportunities: int,
    *,
    label: str,
    family: str,
    context: str,
) -> TendencyEstimate:
    if (
        type(successes) is not int
        or type(opportunities) is not int
        or successes < 0
        or opportunities < 0
        or successes > opportunities
    ):
        raise ValueError("contagens de inteligência competitiva são inválidas")
    observed = successes / opportunities if opportunities else None
    posterior = (successes + PRIOR_ALPHA) / (opportunities + PRIOR_ALPHA + PRIOR_BETA)
    low, high = _wilson95(successes, opportunities)
    if opportunities < MIN_OPPORTUNITIES:
        evidence = "insufficient"
    elif opportunities < STABLE_OPPORTUNITIES:
        evidence = "emerging"
    else:
        evidence = "stable"
    return TendencyEstimate(
        key=key,
        label=label,
        family=family,
        context=context,
        successes=successes,
        opportunities=opportunities,
        observed_rate=round(observed, 4) if observed is not None else None,
        posterior_mean=round(posterior, 4),
        interval95_low=round(low, 4) if low is not None else None,
        interval95_high=round(high, 4) if high is not None else None,
        evidence_fraction=round(min(1.0, opportunities / STABLE_OPPORTUNITIES), 4),
        evidence=evidence,
        ready=opportunities >= MIN_OPPORTUNITIES,
    )


def build_profile(player: dict) -> CompetitiveProfile:
    """Build a read-only profile from one validated ``WatchStats.per`` record."""
    hands = player["hands_dealt"]
    raw: list[tuple[str, int, int, str, str, str]] = [
        ("vpip", player["vpip"], hands, *_METRIC_META["vpip"]),
        ("pfr", player["pfr"], hands, *_METRIC_META["pfr"]),
    ]
    for key, counts in player["ci"].items():
        opportunities, successes = counts
        raw.append((key, successes, opportunities, *_METRIC_META[key]))
    for bucket, (position_hands, vpip, pfr) in player["pos"].items():
        position_label = _POSITION_LABELS[bucket]
        raw.extend(
            [
                (
                    f"position_{bucket}_vpip",
                    vpip,
                    position_hands,
                    f"VPIP — {position_label}",
                    "posição",
                    position_label,
                ),
                (
                    f"position_{bucket}_pfr",
                    pfr,
                    position_hands,
                    f"PFR — {position_label}",
                    "posição",
                    position_label,
                ),
            ]
        )
    for position in EXACT_POSITIONS:
        position_hands, vpip, pfr = player["pos_exact"][position]
        raw.extend(
            [
                (
                    f"position_exact_{position}_vpip",
                    vpip,
                    position_hands,
                    f"VPIP — {position}",
                    "posição exata",
                    position,
                ),
                (
                    f"position_exact_{position}_pfr",
                    pfr,
                    position_hands,
                    f"PFR — {position}",
                    "posição exata",
                    position,
                ),
            ]
        )
    signals = [
        estimate(
            key,
            successes,
            opportunities,
            label=label,
            family=family,
            context=context,
        )
        for key, successes, opportunities, label, family, context in raw
    ]

    actions = player["actions"]
    long_run = player["aggressive"] / actions if actions else None
    ewma = player["ci_ewma_aggression"]
    delta = ewma - long_run if ewma is not None and long_run is not None else None
    recency_ready = actions >= MIN_OPPORTUNITIES
    if not recency_ready or delta is None:
        direction = "insufficient"
    elif delta >= RECENCY_DELTA:
        direction = "more_aggressive"
    elif delta <= -RECENCY_DELTA:
        direction = "more_passive"
    else:
        direction = "stable"
    recency = RecencyEstimate(
        actions=actions,
        ewma_aggression=round(ewma, 4) if ewma is not None else None,
        long_run_aggression=round(long_run, 4) if long_run is not None else None,
        delta=round(delta, 4) if delta is not None else None,
        direction=direction,
        ready=recency_ready,
    )
    return CompetitiveProfile(
        version=PROFILE_VERSION,
        scope="local_session_only",
        authority="descriptive_only_no_action_advice",
        posterior_method="beta-binomial Beta(1,1)",
        interval_method="Wilson score 95% sobre a frequência observada",
        minimum_opportunities=MIN_OPPORTUNITIES,
        signals=signals,
        recency=recency,
    )
