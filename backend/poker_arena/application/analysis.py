"""Análise em tempo real da mão do humano — alimenta os painéis do dashboard.

Tudo é calculado de verdade a partir do estado do motor (sem mock): equity multiway,
outs/projetos, a nut, textura do board, pot odds, EV, SPR, posição, o CONSELHO das 5
IAs (o que cada cérebro recomendaria pra essa jogada) e o perfil do humano. Roda no
turno do humano (modo jogar).
"""

from __future__ import annotations

import logging
import random
from collections import Counter
from collections.abc import Iterable, Sequence
from itertools import combinations

from treys import Card as TCard
from treys import Evaluator as TEvaluator

from ..bots.adaptive_bot import AdaptiveBot
from ..bots.base import Bot
from ..bots.observation import observation_for
from ..bots.opponent_model import OpponentModel
from ..engine.actions import ActionType
from ..engine.cards import Card
from ..engine.game import Hand
from ..engine.player import Player, PlayerStatus
from .bot_factory import ExpertUnavailable, create_bot
from .views import CouncilEntryView, HumanAnalysisView, WinProbView

LOGGER = logging.getLogger(__name__)

_EVAL = TEvaluator()
_FULL = [TCard.new(r + s) for r in "23456789TJQKA" for s in "shdc"]
_ACT_PT = {
    ActionType.FOLD: "Desistir",
    ActionType.CHECK: "Passar",
    ActionType.CALL: "Pagar",
    ActionType.RAISE: "Aumentar",
    ActionType.ALL_IN: "All-in",
}


def _t(cards: Iterable[Card]) -> list[int]:
    return [TCard.new(str(c)) for c in cards]


def _win_probs(
    hero_seat: int,
    hero_hole: Sequence[Card],
    seats: list[int],
    board: Sequence[Card],
    samples: int,
) -> dict[int, float]:
    """Equity pública: conhece só as cartas do herói e amostra os vilões."""
    if hero_seat not in seats:
        raise ValueError("o assento do herói precisa estar entre os contestantes")
    if samples <= 0:
        raise ValueError("samples precisa ser positivo")
    opponents = [s for s in seats if s != hero_seat]
    hero = _t(hero_hole)
    bd = _t(board)
    known = set(hero) | set(bd)
    deck = [c for c in _FULL if c not in known]
    need_board = 5 - len(bd)
    need_total = 2 * len(opponents) + need_board
    if need_total > len(deck):
        raise ValueError("oponentes demais para as cartas disponíveis")
    wins = {s: 0.0 for s in seats}
    rng = random.Random(20260704)  # noqa: S311 - deterministic, reproducible equity estimate
    for _ in range(samples):
        drawn = rng.sample(deck, need_total)
        hands = {s: drawn[i * 2 : i * 2 + 2] for i, s in enumerate(opponents)}
        full = bd + drawn[2 * len(opponents) :]
        scores = {hero_seat: _EVAL.evaluate(full, hero)}
        scores.update({s: _EVAL.evaluate(full, hand) for s, hand in hands.items()})
        best = min(scores.values())
        winners = [s for s in seats if scores[s] == best]
        for s in winners:
            wins[s] += 1.0 / len(winners)
    return {s: wins[s] / samples for s in seats}


def _hand_name(hole: Sequence[Card], board: Sequence[Card]) -> str | None:
    if len(board) < 3:
        return None
    score = _EVAL.evaluate(_t(board), _t(hole))
    return _EVAL.class_to_string(_EVAL.get_rank_class(score))


def _outs_and_draws(hole: Sequence[Card], board: Sequence[Card]) -> tuple[int, list[str]]:
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


def _nut(board: Sequence[Card]) -> str | None:
    if len(board) < 3:
        return None
    bd = _t(board)
    known = set(bd)
    deck = [c for c in _FULL if c not in known]
    best = min(_EVAL.evaluate(bd, list(c)) for c in combinations(deck, 2))
    return _EVAL.class_to_string(_EVAL.get_rank_class(best))


def _texture(board: Sequence[Card]) -> str | None:
    if len(board) < 3:
        return None
    suits = Counter(c.suit for c in board)
    ranks = sorted(int(c.rank) for c in board)
    wet = max(suits.values()) >= 3 or (ranks[-1] - ranks[0]) <= 4
    return "molhado (perigoso)" if wet else "seco (tranquilo)"


def _position(seat: int, button: int, n: int) -> str:
    from .positions import position, position_full

    lbl = position(seat, button, n)
    return f"{lbl} — {position_full(lbl)}" if lbl else "—"


_SUIT_SYM = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}
_RANK_SYM = {14: "A", 13: "K", 12: "Q", 11: "J", 10: "10"}


def _pretty(card: Card) -> str:
    r = int(card.rank)
    return f"{_RANK_SYM.get(r, str(r))}{_SUIT_SYM.get(card.suit.value, card.suit.value)}"


def _realization(seat: int, button: int, players: Sequence[Player]) -> tuple[str, str]:
    """Equity Realization (qualitativa): posição na ordem de ação pós-flop.

    Equity × realização = EV: quem FECHA a ação (em posição) realiza mais da sua
    equity; quem age primeiro (fora de posição) realiza menos. Não cravamos um
    número — isso exigiria um solver — só o sentido, que é exato.
    """
    n = len(players)
    active = [i for i, p in enumerate(players) if p.status == PlayerStatus.ACTIVE]
    if len(active) < 2:
        return "média", ""
    order = sorted(active, key=lambda i: (i - button - 1) % n)
    if order[-1] == seat:
        return "alta", "você fecha a ação (em posição): decide vendo o que todos fizeram"
    if order[0] == seat:
        return "baixa", "você age primeiro (fora de posição): decide no escuro"
    return "média", "você age no meio da ordem de ação"


def _blockers(hole: Sequence[Card], board: Sequence[Card]) -> list[str]:
    """Cartas suas que REMOVEM combos das mãos mais fortes do vilão (aritmética
    de combos, sem simulação). Cobre os dois casos clássicos e verificáveis:
    bloquear o nut flush e bloquear quadra/full house em board pareado."""
    if len(board) < 3:
        return []
    out: list[str] = []
    suits = Counter(c.suit for c in board)
    for suit, cnt in suits.items():
        if cnt >= 3:  # flush possível
            on_board = {int(c.rank) for c in board if c.suit == suit}
            top_missing = next(r for r in range(14, 1, -1) if r not in on_board)
            held = next((c for c in hole if c.suit == suit and int(c.rank) == top_missing), None)
            if held:
                out.append(
                    f"Seu {_pretty(held)} bloqueia o nut flush — o vilão não pode ter a melhor cor"
                )
    rank_counts = Counter(int(c.rank) for c in board)
    for r, cnt in rank_counts.items():
        if cnt >= 2:  # board pareado
            held = next((c for c in hole if int(c.rank) == r), None)
            if held:
                out.append(
                    f"Seu {_pretty(held)} bloqueia quadra/full house — sobram menos combos fortes"
                )
    return out[:2]


def _council_bot(level: str, opp_model: OpponentModel) -> Bot:
    if level == "adaptive":  # usa a leitura REAL do humano
        return AdaptiveBot(opp_model, seed=0)
    # Uma query deve ser referencialmente transparente: bot fresco e seed fixa.
    # Compartilhar instâncias consumia RNG e fazia GET alterar leituras futuras.
    return create_bot(level, seed=0)


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

    active = [i for i, p in enumerate(players) if p.status != PlayerStatus.FOLDED]
    wp = _win_probs(seat, me.hole, active, board, samples) if len(active) >= 2 else {seat: 1.0}
    equity = wp.get(seat, 0.0)

    pot = hand.pot
    to_call = hand.amount_to_call()
    pot_odds = to_call / (pot + to_call) if to_call > 0 else 0.0
    ev_call = equity * (pot + to_call) - to_call
    # MDF (frequência mínima de defesa): 1 − to_call/pote (pote já contém a aposta)
    mdf = (1 - to_call / pot) if (to_call > 0 and pot > 0) else None
    realization, realization_why = _realization(seat, hand.button, players)
    others = [
        p.stack for i, p in enumerate(players) if i != seat and p.status != PlayerStatus.FOLDED
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
        except ExpertUnavailable as exc:
            LOGGER.warning("nível %s indisponível durante conselho: %s", lvl, exc)
            continue
        except Exception:  # noqa: BLE001 - isolate one optional council member
            LOGGER.exception("falha ao calcular o conselho ao vivo do nível %s", lvl)
            continue

    best = next((c for c in council if c.level == "expert"), None) or (
        council[0] if council else None
    )
    profile = opp_model.read()

    return HumanAnalysisView(
        equity=round(equity, 4),
        win_probs=[
            WinProbView(seat=s, prob=round(wp[s], 4)) for s in sorted(wp, key=lambda x: -wp[x])
        ],
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
        mdf=(round(mdf, 4) if mdf is not None else None),
        realization=realization,
        realization_why=realization_why,
        blockers=_blockers(me.hole, board),
    )
