"""Análise em tempo real da mão do humano — alimenta os painéis do dashboard.

Tudo é calculado de verdade a partir do estado do motor (sem mock): equity multiway,
outs/projetos, a nut, textura do board, pot odds, EV, SPR, posição, o CONSELHO das 5
IAs (o que cada cérebro recomendaria pra essa jogada) e o perfil do humano. Roda no
turno do humano (modo jogar).
"""

from __future__ import annotations

import random
from collections import Counter
from itertools import combinations

from treys import Card as TCard
from treys import Evaluator as TEvaluator

from ..bots.adaptive_bot import AdaptiveBot
from ..bots.observation import observation_for
from ..bots.opponent_model import OpponentModel
from ..engine.actions import ActionType
from ..engine.game import Hand
from ..engine.player import PlayerStatus
from .bot_factory import ExpertUnavailable, create_bot
from .views import CouncilEntryView, HumanAnalysisView, WinProbView

_EVAL = TEvaluator()
_FULL = [TCard.new(r + s) for r in "23456789TJQKA" for s in "shdc"]
_RNG = random.Random()
_ACT_PT = {
    ActionType.FOLD: "Desistir",
    ActionType.CHECK: "Passar",
    ActionType.CALL: "Pagar",
    ActionType.RAISE: "Aumentar",
    ActionType.ALL_IN: "All-in",
}
_COUNCIL: dict[str, object] = {}  # cache (o Expert carrega o ONNX uma vez só)


def _t(cards) -> list[int]:
    return [TCard.new(str(c)) for c in cards]


def _win_probs(holes: dict[int, list], board, samples: int) -> dict[int, float]:
    """% de vitória real de cada assento, com as cartas conhecidas (showdown sim)."""
    seats = list(holes)
    my = {s: _t(holes[s]) for s in seats}
    bd = _t(board)
    known = {c for h in my.values() for c in h} | set(bd)
    deck = [c for c in _FULL if c not in known]
    need = 5 - len(bd)
    wins = {s: 0.0 for s in seats}
    runs = 1 if need == 0 else samples
    for _ in range(runs):
        full = bd if need == 0 else bd + (_RNG.sample(deck, need))
        scores = {s: _EVAL.evaluate(full, my[s]) for s in seats}
        best = min(scores.values())
        winners = [s for s in seats if scores[s] == best]
        for s in winners:
            wins[s] += 1.0 / len(winners)
    return {s: wins[s] / runs for s in seats}


def _hand_name(hole, board) -> str | None:
    if len(board) < 3:
        return None
    score = _EVAL.evaluate(_t(board), _t(hole))
    return _EVAL.class_to_string(_EVAL.get_rank_class(score))


def _outs_and_draws(hole, board) -> tuple[int, list[str]]:
    if not (3 <= len(board) < 5):
        return 0, []
    my, bd = _t(hole), _t(board)
    cur = _EVAL.get_rank_class(_EVAL.evaluate(bd, my))
    known = set(my) | set(bd)
    deck = [c for c in _FULL if c not in known]
    outs = sum(1 for c in deck if _EVAL.get_rank_class(_EVAL.evaluate([*bd, c], my)) < cur)
    draws: list[str] = []
    cards = list(hole) + list(board)
    if max(Counter(c.suit for c in cards).values()) == 4:
        draws.append("projeto de flush")
    ranks = sorted({int(c.rank) for c in cards})
    if any(ranks[i + 3] - ranks[i] == 3 for i in range(len(ranks) - 3)):
        draws.append("projeto de sequência")
    return outs, draws


def _nut(board) -> str | None:
    if len(board) < 3:
        return None
    bd = _t(board)
    known = set(bd)
    deck = [c for c in _FULL if c not in known]
    best = min(_EVAL.evaluate(bd, list(c)) for c in combinations(deck, 2))
    return _EVAL.class_to_string(_EVAL.get_rank_class(best))


def _texture(board) -> str | None:
    if len(board) < 3:
        return None
    suits = Counter(c.suit for c in board)
    ranks = sorted(int(c.rank) for c in board)
    wet = max(suits.values()) >= 3 or (ranks[-1] - ranks[0]) <= 4
    return "molhado (perigoso)" if wet else "seco (tranquilo)"


def _position(seat: int, button: int, n: int) -> str:
    rel = (seat - button) % n
    if rel == 0:
        return "Botão (D)"
    if rel == 1:
        return "Small blind"
    if rel == 2:
        return "Big blind"
    return "Posição cedo" if rel <= n // 2 else "Posição tarde"


def _council_bot(level: str, opp_model: OpponentModel):
    if level == "adaptive":  # usa a leitura REAL do humano
        return AdaptiveBot(opp_model)
    if level not in _COUNCIL:
        _COUNCIL[level] = create_bot(level)
    return _COUNCIL[level]


def analyze(
    hand: Hand,
    seat: int,
    opp_model: OpponentModel,
    available_levels: list[str],
    *,
    samples: int = 250,
) -> HumanAnalysisView:
    players = hand.players
    me = players[seat]
    board = hand.board

    active = {
        i: p.hole
        for i, p in enumerate(players)
        if p.status != PlayerStatus.FOLDED and p.hole
    }
    wp = _win_probs(active, board, samples) if len(active) >= 2 else {seat: 1.0}
    equity = wp.get(seat, 0.0)

    pot = hand.pot
    to_call = hand.amount_to_call()
    pot_odds = to_call / (pot + to_call) if to_call > 0 else 0.0
    ev_call = equity * (pot + to_call) - (1 - equity) * to_call
    others = [
        p.stack
        for i, p in enumerate(players)
        if i != seat and p.status != PlayerStatus.FOLDED
    ]
    eff = min(me.stack, max(others, default=me.stack))
    spr = round(eff / pot, 1) if pot else None
    outs, draws = _outs_and_draws(me.hole, board)

    # conselho das IAs: o que cada cérebro faria nessa MESMA jogada
    obs = observation_for(hand)
    council: list[CouncilEntryView] = []
    for lvl in ("expert", "adaptive", "montecarlo", "heuristic", "random"):
        if lvl == "expert" and "expert" not in available_levels:
            continue
        try:
            bot = _council_bot(lvl, opp_model)
            act = bot.act(obs)
            ins = bot.insight() if hasattr(bot, "insight") else None
            council.append(
                CouncilEntryView(
                    level=lvl,
                    action=_ACT_PT.get(act.type, act.type.value),
                    amount=act.amount,
                    confidence=(round(ins.confidence, 3) if ins else None),
                )
            )
        except (ExpertUnavailable, Exception):
            continue

    best = next((c for c in council if c.level == "expert"), None) or (
        council[0] if council else None
    )
    profile = opp_model.read()

    return HumanAnalysisView(
        equity=round(equity, 4),
        win_probs=[WinProbView(seat=s, prob=round(wp[s], 4)) for s in sorted(wp, key=lambda x: -wp[x])],
        hand_name=_hand_name(me.hole, board),
        outs=outs,
        draws=draws,
        pot_odds=round(pot_odds, 4),
        ev_call=round(ev_call, 1),
        nut=_nut(board),
        texture=_texture(board),
        spr=spr,
        position=_position(seat, hand.button, len(players)),
        council=council,
        best_action=best.action if best else None,
        best_amount=best.amount if best else None,
        confidence=best.confidence if best else None,
        your_profile_fold=round(profile.fold_to_bet, 2),
        your_profile_aggr=round(profile.aggression, 2),
        your_profile_samples=profile.samples,
    )
