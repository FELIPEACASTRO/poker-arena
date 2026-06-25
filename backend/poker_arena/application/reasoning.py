"""Explica, de forma DIDÁTICA, como o bot que acabou de jogar está pensando.

Para cada jogada no Modo Laboratório, monta:
- como aquele paradigma de IA raciocina;
- o que ele viu (mão, chance real de ganhar, pote, preço pra pagar);
- as jogadas possíveis avaliadas (boa/arriscada/ruim) e POR QUÊ — usando poker de
  verdade (equity x pot odds), calculado por simulação (sem mock);
- por que ESTE cérebro escolheu ESTA jogada (com o número real que ele usou).

A 'chance real' é a equity vs oponentes aleatórios (o número que faz sentido pra
decidir, já que o bot não vê as cartas alheias) — a mesma conta do MonteCarloBot.
"""

from __future__ import annotations

import random

from ..bots.insight import BotInsight
from ..bots.monte_carlo_bot import estimate_equity
from ..bots.observation import Observation
from ..engine.actions import Action, ActionType
from .analysis import _hand_name
from .views import OptionView, ReasoningView

_RNG = random.Random()
_EQUITY_SAMPLES = 160
_VALUE = 0.66  # acima disso, mão "forte o bastante" para apostar por valor

_HOW = {
    "random": "O Iniciante não calcula nada — escolhe uma jogada válida no chute. É a linha de base pra comparar com quem pensa.",
    "heuristic": "O Amador mede a FORÇA da mão por regras (pares, cartas altas, naipe) e segue pot odds — mas não simula o futuro.",
    "montecarlo": "O Intermediário SIMULA centenas de finais de mão pra estimar a chance real de ganhar (equity) e compara com o preço.",
    "adaptive": "O Adaptativo parte da força da mão e AJUSTA pela leitura do oponente: contra quem desiste muito, blefa mais; contra quem paga tudo, só aposta valor.",
    "expert": "O Expert é uma rede neural treinada (solver + self-play): aprendeu a melhor jogada e dá a probabilidade de cada ação.",
}
_VERB = {
    ActionType.FOLD: "DESISTIR",
    ActionType.CHECK: "PASSAR",
    ActionType.CALL: "PAGAR",
    ActionType.RAISE: "AUMENTAR",
    ActionType.ALL_IN: "ir de ALL-IN",
}
_PAST = {
    ActionType.FOLD: "desistiu",
    ActionType.CHECK: "passou",
    ActionType.CALL: "pagou",
    ActionType.RAISE: "aumentou",
    ActionType.ALL_IN: "foi all-in",
}
_ORDER = [ActionType.FOLD, ActionType.CHECK, ActionType.CALL, ActionType.RAISE, ActionType.ALL_IN]
_SYM = {14: "A", 13: "K", 12: "Q", 11: "J", 10: "10"}


def _preflop_label(hole) -> str:
    a, b = int(hole[0].rank), int(hole[1].rank)
    sa, sb = _SYM.get(a, str(a)), _SYM.get(b, str(b))
    if a == b:
        return f"Par de {sa}"
    suited = " (mesmo naipe)" if hole[0].suit == hole[1].suit else ""
    hi, lo = (sa, sb) if a >= b else (sb, sa)
    return f"{hi}-{lo}{suited}"


def _option(
    act: ActionType, obs: Observation, eq: int, po: int, chosen: bool, amount: int
) -> OptionView:
    """Avalia uma jogada possível com poker de verdade (equity x pot odds)."""
    if act == ActionType.FOLD:
        label = "Desistir"
        if obs.to_call == 0:
            v, r = "bad", "Dá pra passar de graça — desistir aqui joga a mão fora à toa."
        elif eq < po:
            v, r = "good", f"Sua chance ({eq}%) é menor que o preço ({po}%): pagar perderia fichas no longo prazo, então largar é o certo."
        else:
            v, r = "bad", f"Você ainda ganha mais ({eq}%) do que o preço pede ({po}%) — desistir joga fora uma mão lucrativa."
    elif act == ActionType.CHECK:
        label = "Passar"
        if eq >= _VALUE * 100:
            v, r = "ok", f"Vê a próxima carta de graça — mas com mão forte ({eq}%) dava pra apostar por valor."
        else:
            v, r = "good", "Não custa nada ver a próxima carta — seguro com mão média ou fraca."
    elif act == ActionType.CALL:
        label = f"Pagar {obs.to_call}"
        if eq >= po:
            v, r = "good", f"Sua chance ({eq}%) é maior que o preço ({po}%): pagar dá lucro no longo prazo."
        else:
            v, r = "bad", f"Você paga por {po}% mas só ganha {eq}%: no longo prazo, pagar perde fichas."
    elif act == ActionType.RAISE:
        label = f"Aumentar p/ {amount}" if (chosen and amount) else "Aumentar"
        if eq >= _VALUE * 100:
            v, r = "good", f"Mão forte ({eq}%): aumentar cresce o pote enquanto você está na frente (aposta de valor)."
        elif eq >= po:
            v, r = "ok", f"Arriscado: a mão ({eq}%) não é forte o bastante pra apostar por valor (ideal ~{round(_VALUE * 100)}%+). Só compensa como blefe contra quem desiste fácil."
        else:
            v, r = "bad", f"Blefe puro: mão fraca ({eq}%) — coloca fichas em risco sem estar na frente."
    else:  # ALL_IN
        label = "All-in"
        if eq >= 75:
            v, r = "good", f"Mão muito forte ({eq}%): vale colocar tudo no meio."
        elif eq >= po:
            v, r = "ok", f"Agressivo demais: só compensa com mão muito forte ou como blefe pesado ({eq}%)."
        else:
            v, r = "bad", f"Tudo no risco com mão fraca ({eq}%) — joga muito no escuro."
    return OptionView(action=act.value, label=label, verdict=v, reason=r, chosen=chosen)


def _why(level: str, name: str, past: str, sig: int | None, eq: int, po: int,
         to_call: int, insight: BotInsight | None) -> str:
    """Por que ESTE cérebro escolheu ESTA jogada — com o número real que ele usou."""
    if level == "random":
        return f"{name} escolheu {past} no chute — o Iniciante não pondera nada."
    if level == "expert":
        s = f" ({sig}%)" if sig is not None else ""
        return f"A rede neural deu a maior probabilidade pra essa ação{s}, então {name} {past}."
    if level == "adaptive" and insight is not None:
        return f"{name} ajustou a força da mão pela leitura do oponente ({insight.label}) e {past}."
    # heuristic / montecarlo: sinal x preço/limiar
    base = "simulou e viu" if level == "montecarlo" else "estimou força de"
    sigtxt = f"{sig}%" if sig is not None else "—"
    if to_call == 0:
        return f"{name} {base} {sigtxt}: sem aposta a pagar e sem mão forte o bastante pra apostar por valor, {past}."
    return f"{name} {base} {sigtxt}; comparado ao preço ({po}%), isso indicou {past}."


def explain(
    name: str, level: str, obs: Observation, action: Action, insight: BotInsight | None
) -> ReasoningView:
    n_opp = max(obs.num_active - 1, 1)
    equity = estimate_equity(obs.hole, obs.board, n_opp, _EQUITY_SAMPLES, _RNG)
    pot_odds = obs.to_call / (obs.pot + obs.to_call) if obs.to_call > 0 else 0.0
    eq, po = round(equity * 100), round(pot_odds * 100)
    sig = round(insight.confidence * 100) if insight else None

    hand_label = _hand_name(obs.hole, obs.board)
    if hand_label is None:
        hand_label = _preflop_label(obs.hole)

    options = [
        _option(act, obs, eq, po, chosen=(act == action.type), amount=action.amount)
        for act in _ORDER
        if act in obs.legal_actions
    ]
    past = _PAST.get(action.type, action.type.value)

    return ReasoningView(
        seat=obs.seat,
        name=name,
        level=level,
        action=action.type.value,
        headline=f"{name} vai {_VERB.get(action.type, action.type.value)}",
        how_it_thinks=_HOW.get(level, ""),
        signal_label=(insight.label if insight else None),
        signal_value=(round(insight.confidence, 3) if insight else None),
        hand_label=hand_label,
        equity_pct=eq,
        pot=obs.pot,
        to_call=obs.to_call,
        pot_odds_pct=po,
        options=options,
        why_chosen=_why(level, name, past, sig, eq, po, obs.to_call, insight),
    )
