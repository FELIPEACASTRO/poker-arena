"""Copiloto de revisão de mãos — análise pós-jogo de um SPOT que você descreve.

O "copiloto" que se pediu: você diz suas cartas, o board, o pote, quanto custa
pagar, seu stack e a posição — e ele devolve a leitura COMPLETA (equity real, pot
odds, EV, MDF, outs/projetos, a nut, textura, blockers, realização da equity), o
veredito de CADA jogada possível (boa/arriscada/ruim + por quê) e o conselho das 5
IAs. Tudo calculado de verdade, offline, sem tocar em site nenhum — é o mesmo motor
do painel "Sua jogada", aplicado a qualquer situação.

Como você não vê as cartas dos oponentes (situação REAL de revisão), a equity é
estimada por Monte Carlo contra mãos desconhecidas — exatamente a conta honesta que
um jogador faz na mesa.
"""

from __future__ import annotations

import random

from ..bots.monte_carlo_bot import estimate_equity
from ..bots.observation import Observation, PublicPlayer
from ..engine.actions import Action, ActionType
from ..engine.cards import Card
from ..engine.evaluator import card_from_str
from .analysis import (
    _blockers,
    _council_bot,
    _hand_name,
    _nut,
    _outs_and_draws,
    _texture,
)
from .reasoning import _ORDER, _gto_numbers, _option, _preflop_label
from .views import CopilotView, CouncilEntryView, OptionView

_ACT_PT = {
    ActionType.FOLD: "Desistir",
    ActionType.CHECK: "Passar",
    ActionType.CALL: "Pagar",
    ActionType.RAISE: "Aumentar",
    ActionType.ALL_IN: "All-in",
}


class InvalidSpotError(ValueError):
    """Entrada de spot inválida (cartas repetidas, quantidade errada, etc.)."""


def _parse_cards(items: list[str]) -> list[Card]:
    out: list[Card] = []
    for s in items:
        s = s.strip()
        if not s:
            continue
        try:
            out.append(card_from_str(s[0].upper() + s[1].lower()))
        except Exception as e:
            raise InvalidSpotError(f"carta inválida: {s!r} (use ex.: As, Kd, Th, 7c)") from e
    return out


def _legal_actions(to_call: int, my_stack: int, min_raise_inc: int) -> frozenset[ActionType]:
    acts: set[ActionType] = set()
    if to_call > 0:
        acts.add(ActionType.FOLD)
        if my_stack > 0:
            acts.add(ActionType.CALL)
    else:
        acts.add(ActionType.CHECK)
    if my_stack > to_call + min_raise_inc:  # dá pra fazer um aumento cheio
        acts.add(ActionType.RAISE)
    if my_stack > 0:
        acts.add(ActionType.ALL_IN)
    return frozenset(acts)


def review_spot(
    hole_cards: list[str],
    board_cards: list[str],
    pot: int,
    to_call: int,
    my_stack: int,
    num_opponents: int,
    in_position: bool,
    available_levels: list[str],
    *,
    big_blind: int = 20,
    samples: int = 400,
) -> CopilotView:
    """Analisa um spot descrito pelo usuário e devolve a leitura do copiloto."""
    hole = _parse_cards(hole_cards)
    board = _parse_cards(board_cards)
    if len(hole) != 2:
        raise InvalidSpotError("informe exatamente 2 cartas suas (ex.: As Kh)")
    if len(board) not in (0, 3, 4, 5):
        raise InvalidSpotError(
            "o board deve ter 0 (pré-flop), 3 (flop), 4 (turn) ou 5 (river) cartas"
        )
    all_cards = hole + board
    if len({str(c) for c in all_cards}) != len(all_cards):
        raise InvalidSpotError("há cartas repetidas entre a sua mão e o board")
    if pot < 0 or to_call < 0 or my_stack <= 0 or num_opponents < 1:
        raise InvalidSpotError("valores inválidos (pote/preço ≥ 0, stack > 0, ≥ 1 oponente)")

    n_opp = num_opponents
    # seed FIXO: o mesmo spot dá sempre a mesma leitura (reprodutível pra estudo)
    equity = estimate_equity(hole, board, n_opp, samples, random.Random(20260704))
    eq = round(equity * 100)
    pot_odds = to_call / (pot + to_call) if to_call > 0 else 0.0
    po = round(pot_odds * 100)
    ev_call = equity * (pot + to_call) - (1 - equity) * to_call

    # observação sintética (hero no assento 0) — alimenta os vereditos e o conselho
    min_raise_inc = max(to_call, big_blind)
    current_bet = to_call
    legal = _legal_actions(to_call, my_stack, min_raise_inc)
    players = (
        PublicPlayer(0, "Você", my_stack, 0, 0, "active", not in_position),
        *(
            PublicPlayer(i + 1, f"Vilão {i + 1}", my_stack, current_bet if i == 0 else 0,
                         0, "active", False)
            for i in range(n_opp)
        ),
    )
    obs = Observation(
        seat=0, hole=tuple(hole), board=tuple(board), pot=pot, to_call=to_call,
        current_bet=current_bet, min_raise_to=current_bet + min_raise_inc,
        legal_actions=legal, players=players, num_active=n_opp + 1,
    )

    # veredito de cada jogada possível (reaproveita o motor didático do laboratório)
    options: list[OptionView] = [
        _option(act, obs, eq, po, chosen=False, amount=obs.min_raise_to)
        for act in _ORDER
        if act in legal
    ]

    # conselho das 5 IAs neste MESMO spot
    council: list[CouncilEntryView] = []
    from ..bots.opponent_model import OpponentModel  # leitura neutra (revisão, sem histórico)

    opp_model = OpponentModel()
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
                    confidence=(
                        round(ins.confidence, 3)
                        if ins and ins.confidence is not None
                        else None
                    ),
                )
            )
        except Exception:
            continue

    # recomendação = a MATEMÁTICA (determinística e sólida). Não segue o voto do
    # Expert (que é 6-max, usa estratégia mista e pode errar num spot fora da sua
    # distribuição) — o Expert aparece só no conselho, como opinião.
    rec_type, rec_amount = _recommend(obs, equity, po, legal)
    mdf_pct, _alpha = _gto_numbers(obs, Action(rec_type, amount=rec_amount))
    # marca a opção recomendada como "chosen"
    options = [
        OptionView(o.action, o.label, o.verdict, o.reason, chosen=(o.action == rec_type.value))
        for o in options
    ]
    rec_label = _label_for(rec_type, obs, rec_amount)
    realization, realization_why = (
        ("alta", "você fecha a ação (em posição): decide vendo o que os outros fizeram")
        if in_position
        else ("baixa", "você age primeiro (fora de posição): decide no escuro")
    )

    hand_label = _hand_name(hole, board) or _preflop_label(hole)
    outs, draws = _outs_and_draws(hole, board)

    return CopilotView(
        hand_label=hand_label,
        equity_pct=eq,
        pot=pot,
        to_call=to_call,
        pot_odds_pct=po,
        ev_call=round(ev_call, 1),
        mdf_pct=mdf_pct,
        outs=outs,
        draws=draws,
        nut=_nut(board),
        texture=_texture(board),
        blockers=_blockers(hole, board),
        spr=(round(min(my_stack, my_stack) / pot, 1) if pot else None),
        realization=realization,
        realization_why=realization_why,
        options=options,
        council=council,
        recommendation=rec_type.value,
        recommendation_label=rec_label,
        headline=_headline(rec_type, eq, po, to_call, ev_call),
    )


_VALUE = 0.66  # equity acima disso = mão de valor (vale apostar/aumentar)


def _recommend(obs, equity, po, legal) -> tuple[ActionType, int]:
    """Jogada recomendada SÓ pela matemática (determinística e sólida): equity vs
    preço vs limiar de valor. Nunca desiste de um pagamento lucrativo."""
    if obs.to_call == 0:  # sem aposta: apostar por valor com mão forte, senão passar
        if equity >= _VALUE and ActionType.RAISE in legal:
            return ActionType.RAISE, obs.min_raise_to
        return ActionType.CHECK, 0
    # enfrentando aposta:
    if equity >= _VALUE and ActionType.RAISE in legal:
        return ActionType.RAISE, obs.min_raise_to  # mão forte -> aumenta por valor
    if equity >= po / 100:  # pagar é lucrativo
        if ActionType.CALL in legal:
            return ActionType.CALL, 0
        if ActionType.ALL_IN in legal:  # stack curto: pagar equivale a all-in
            return ActionType.ALL_IN, 0
    return ActionType.FOLD, 0


def _label_for(t: ActionType, obs, amount: int) -> str:
    if t == ActionType.CALL:
        return f"Pagar {obs.to_call}"
    if t == ActionType.RAISE:
        return f"Aumentar p/ {amount}"
    return _ACT_PT.get(t, t.value)


def _headline(t: ActionType, eq: int, po: int, to_call: int, ev: float) -> str:
    if t == ActionType.FOLD:
        return f"Recomendo DESISTIR: sua chance ({eq}%) não cobre o preço ({po}%) — pagar perde fichas."
    if t == ActionType.CHECK:
        return f"Recomendo PASSAR: sem aposta e mão de {eq}%, veja a próxima carta de graça."
    if t == ActionType.CALL:
        return f"Recomendo PAGAR: {eq}% de chance contra {po}% de preço — EV +{round(ev, 1)} fichas."
    if t == ActionType.RAISE:
        return f"Recomendo AUMENTAR: mão forte ({eq}%) — cresça o pote estando na frente (valor)."
    return f"Recomendo ALL-IN: mão muito forte ({eq}%)."
