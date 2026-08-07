"""Explica, de forma DIDÁTICA, como o bot que acabou de jogar está pensando.

Para cada jogada no Modo Laboratório, monta:
- como aquele paradigma de IA raciocina;
- o que ele viu (equity estimada, pote, preço pra pagar);
- as jogadas possíveis avaliadas (boa/arriscada/ruim) e POR QUÊ — usando poker de
  verdade (equity x pot odds), calculado por simulação (sem mock);
- por que ESTE cérebro escolheu ESTA jogada (com o número real que ele usou).

A equity é estimada contra mãos aleatórias, pois o bot não vê as cartas alheias.
Ela é um modelo explícito, não a probabilidade verdadeira contra qualquer população.
"""

from __future__ import annotations

import random
from collections.abc import Sequence

from ..bots.insight import BotInsight
from ..bots.monte_carlo_bot import estimate_equity
from ..bots.observation import Observation
from ..engine.actions import Action, ActionType
from ..engine.cards import Card
from .analysis import _hand_name
from .views import OptionView, ReasoningView

_PHRASE_RNG = random.SystemRandom()
_EQUITY_SAMPLES = 1_000
_VALUE = 0.66  # acima disso, mão "forte o bastante" para apostar por valor

# Vários jeitos de explicar cada paradigma — sorteia um por jogada (não repete tanto).
_HOW = {
    "random": [
        "O Iniciante não calcula nada — escolhe uma jogada válida no chute. É a linha de base pra comparar com quem pensa.",
        "O Iniciante joga no sorteio: pega qualquer ação permitida, sem olhar a força da mão. Serve pra você ver a diferença pra quem raciocina.",
        "Aqui não há estratégia: o Iniciante decide no cara ou coroa entre o que é legal jogar.",
    ],
    "heuristic": [
        "O Amador mede a FORÇA da mão por regras (pares, cartas altas, naipe) e segue pot odds — mas não simula o futuro.",
        "O Amador segue um 'manual' de regras pra dar uma nota à mão e compara essa nota com o preço de pagar. Rápido, mas sem imaginar como a mão termina.",
        "O Amador olha as cartas e aplica regras fixas (par? cartas altas? mesmo naipe?) pra estimar a força e decidir.",
    ],
    "montecarlo": [
        "O Intermediário simula centenas de finais contra mãos aleatórias para estimar equity e comparar com o preço.",
        "O Intermediário 'joga o futuro' na cabeça muitas vezes: distribui cartas aleatórias pros adversários, vê quem ganharia e mede a sua chance — depois compara com o preço.",
        "Aqui entra a matemática: o Intermediário roda centenas de simulações da mão até o fim pra saber, na média, quanto você ganha.",
    ],
    "adaptive": [
        "O Adaptativo parte da força da mão e AJUSTA pela leitura do oponente: contra quem desiste muito, blefa mais; contra quem paga tudo, só aposta valor.",
        "O Adaptativo é o mais 'humano': além da força da mão, ele observa o seu jeito de jogar e explora — pressiona quem foge e respeita quem paga tudo.",
        "Ele combina força da mão com psicologia: aprende o seu estilo e usa isso a favor dele (blefa contra medroso, aposta valor contra teimoso).",
    ],
    "expert": [
        "O Expert é uma política neural experimental: produz escores para cinco ações, sem garantia de estratégia ótima.",
        "O Expert usa um modelo ONNX treinado offline; sua força depende dos dados e benchmarks registrados no model card.",
        "Aqui há aprendizado de máquina, mas a saída é uma recomendação empírica — não uma prova de GTO nem uma solução do jogo.",
    ],
}
_VERB = {
    ActionType.FOLD: "DESISTIR",
    ActionType.CHECK: "PASSAR",
    ActionType.CALL: "PAGAR",
    ActionType.RAISE: "AUMENTAR",
    ActionType.ALL_IN: "de ALL-IN",
}
_PAST = {
    ActionType.FOLD: "desistiu",
    ActionType.CHECK: "passou",
    ActionType.CALL: "pagou",
    ActionType.RAISE: "aumentou",
    ActionType.ALL_IN: "foi all-in",
}
_INF = {  # infinitivo (pra frases como "decidiu pagar", "escolheu desistir")
    ActionType.FOLD: "desistir",
    ActionType.CHECK: "passar",
    ActionType.CALL: "pagar",
    ActionType.RAISE: "aumentar",
    ActionType.ALL_IN: "ir de all-in",
}
_ORDER = [ActionType.FOLD, ActionType.CHECK, ActionType.CALL, ActionType.RAISE, ActionType.ALL_IN]
_SYM = {14: "A", 13: "K", 12: "Q", 11: "J", 10: "10"}


def _preflop_label(hole: Sequence[Card]) -> str:
    a, b = int(hole[0].rank), int(hole[1].rank)
    sa, sb = _SYM.get(a, str(a)), _SYM.get(b, str(b))
    if a == b:
        return f"Par de {sa}"
    suited = " (mesmo naipe)" if hole[0].suit == hole[1].suit else ""
    hi, lo = (sa, sb) if a >= b else (sb, sa)
    return f"{hi}-{lo}{suited}"


def _pick(*variants: str) -> str:
    """Sorteia uma das formas de dizer a mesma coisa (variedade sem perder o sentido)."""
    return _PHRASE_RNG.choice(variants)


def _option(
    act: ActionType,
    obs: Observation,
    eq: int,
    po: int,
    chosen: bool,
    amount: int,
    *,
    equity_rate: float | None = None,
    pot_odds_rate: float | None = None,
    decision_margin: float = 0.0,
) -> OptionView:
    """Avalia uma jogada possível com poker de verdade (equity x pot odds)."""
    equity_value = eq / 100 if equity_rate is None else equity_rate
    pot_odds_value = po / 100 if pot_odds_rate is None else pot_odds_rate
    call_threshold = pot_odds_value + decision_margin
    value_threshold = _VALUE + decision_margin
    call_threshold_pct = round(call_threshold * 100)
    val = round(value_threshold * 100)
    adjustment = (
        f"limiar ajustado de {call_threshold_pct}% (preço {po}% + posição)"
        if decision_margin > 0
        else f"preço de {po}%"
    )
    if act == ActionType.FOLD:
        label = "Desistir"
        if obs.to_call == 0:
            v = "bad"
            r = _pick(
                "Dá pra passar de graça — desistir aqui joga a mão fora à toa.",
                "Não há nada a pagar: largar a mão agora seria desperdício.",
                "Sem aposta na mesa, desistir é só jogar fora uma chance grátis.",
            )
        elif equity_value < call_threshold:
            v = "good"
            r = f"Sua chance ({eq}%) fica abaixo do {adjustment}; a heurística recomenda desistir."
        else:
            v = "bad"
            r = f"Sua chance ({eq}%) cobre o {adjustment}; desistir contraria esta heurística."
    elif act == ActionType.CHECK:
        label = "Passar"
        if equity_value >= value_threshold:
            v = "ok"
            r = _pick(
                f"Vê a próxima carta de graça — mas com mão forte ({eq}%) dava pra apostar por valor.",
                f"Passar é seguro, mas desperdiça uma mão forte ({eq}%): dava pra construir o pote.",
            )
        else:
            v = "good"
            r = _pick(
                "Não custa nada ver a próxima carta — seguro com mão média ou fraca.",
                "Como não há aposta, passar deixa você ver mais uma carta sem gastar fichas.",
                "Jogada econômica: espia o próximo lance de graça e evita se comprometer com mão mediana.",
            )
    elif act == ActionType.CALL:
        label = f"Pagar {obs.to_call}"
        if equity_value >= call_threshold:
            v = "good"
            r = f"Sua chance ({eq}%) cobre o {adjustment}; pagar passa o limiar da heurística."
        else:
            v = "bad"
            r = f"Sua chance ({eq}%) fica abaixo do {adjustment}; pagar não passa o limiar."
    elif act == ActionType.RAISE:
        label = f"Aumentar p/ {amount}" if (chosen and amount) else "Aumentar"
        if equity_value >= value_threshold:
            v = "good"
            r = _pick(
                f"Mão forte ({eq}%): aumentar cresce o pote enquanto você está na frente (aposta de valor).",
                f"Com {eq}% de chance você está na liderança — aumentar extrai fichas dos adversários.",
            )
        elif equity_value >= call_threshold:
            v = "ok"
            r = _pick(
                f"Arriscado: a mão ({eq}%) não é forte o bastante pra apostar por valor (ideal ~{val}%+). Só compensa como blefe contra quem desiste fácil.",
                f"Meio-termo perigoso: {eq}% não é mão de valor (precisaria ~{val}%+). Só vale como blefe contra adversário medroso.",
            )
        else:
            v = "bad"
            r = _pick(
                f"Blefe puro: mão fraca ({eq}%) — coloca fichas em risco sem estar na frente.",
                f"Aumentar com {eq}% é apostar no escuro: você raramente está na frente, é fichas no risco.",
            )
    else:  # ALL_IN
        me = next(player for player in obs.players if player.seat == obs.seat)
        all_in_is_call = obs.to_call > 0 and me.stack <= obs.to_call
        label = f"All-in para pagar {me.stack}" if all_in_is_call else "All-in"
        if all_in_is_call and equity_value >= call_threshold:
            v = "good"
            r = f"É o call curto canônico: {eq}% cobre o {adjustment}; não é uma agressão."
        elif all_in_is_call:
            v = "bad"
            r = f"É um call curto, mas {eq}% fica abaixo do {adjustment}."
        elif equity_value >= value_threshold:
            v = "good"
            r = f"Mão de valor ({eq}%) supera o limiar ajustado de {val}% para a agressão."
        elif equity_value >= call_threshold:
            v = "ok"
            r = _pick(
                f"Agressivo demais: só compensa com mão muito forte ou como blefe pesado ({eq}%).",
                f"All-in com {eq}% é ousado — funciona como blefe forte, mas o risco é alto.",
            )
        else:
            v = "bad"
            r = _pick(
                f"Tudo no risco com mão fraca ({eq}%) — joga muito no escuro.",
                f"Apostar todas as fichas com {eq}% é quase um tiro no escuro.",
            )
    return OptionView(action=act.value, label=label, verdict=v, reason=r, chosen=chosen)


def _why(
    level: str,
    name: str,
    past: str,
    inf: str,
    sig: int | None,
    eq: int,
    po: int,
    to_call: int,
    insight: BotInsight | None,
) -> str:
    """Por que ESTE cérebro escolheu ESTA jogada — com o número real que ele usou."""
    first = name.split()[0]
    if level == "random":
        return _pick(
            f"{name} foi de {inf} no chute — o Iniciante não pondera nada, é pura sorte.",
            f"Sem cálculo nenhum: {name} sorteou {inf} entre as jogadas possíveis.",
            f"{name} jogou {inf} na loteria — o Iniciante decide no acaso.",
        )
    if level == "expert":
        s = f" ({sig}%)" if sig is not None else ""
        return _pick(
            f"A rede neural deu a maior probabilidade para {inf}{s}, e foi isso que {name} fez.",
            f"O modelo treinado apontou {inf}{s} como a melhor ação, então {name} {past}.",
        )
    if level == "adaptive" and insight is not None:
        return _pick(
            f"{name} partiu da força da mão e ajustou pela leitura do oponente ({insight.label}); por isso {past}.",
            f"Misturando a mão com a leitura do adversário ({insight.label}), {name} {past}.",
        )
    # heuristic / montecarlo: sinal x preço/limiar
    base = "simulou várias vezes e viu" if level == "montecarlo" else "calculou a força da mão em"
    sigtxt = f"{sig}%" if sig is not None else "—"
    if to_call == 0:
        return _pick(
            f"{name} {base} {sigtxt}: como não há nada a pagar e a mão não é forte o bastante para apostar por valor, o melhor era {inf} — e foi o que {first} fez.",
            f"Com {sigtxt} e nada a pagar, não dava pra apostar por valor: {name} preferiu {inf}.",
        )
    return _pick(
        f"{name} {base} {sigtxt} e comparou com o preço ({po}%); a conta apontou para {inf}, então {past}.",
        f"Botando {sigtxt} contra o preço de {po}%, a matemática levou {name} a {inf}.",
    )


def _gto_numbers(obs: Observation, action: Action) -> tuple[int | None, int | None]:
    """MDF e α (fold equity do blefe) — fórmulas fechadas de GTO, didáticas.

    - Enfrentando aposta: quem paga precisa de equity α = to_call/pote; o MDF
      (frequência mínima de defesa) do defensor é 1 − α. Ex. verificado: aposta 60
      num pote de 100 → pote fica 160 → α = 37,5%, MDF = 62,5%.
    - Ao apostar/aumentar: um blefe puro lucra se os rivais desistem mais que
      α = risco / (risco + recompensa), com risco = fichas que o bot adiciona e
      recompensa = pote atual. Referência teórica (heads-up/river).
    """
    mdf_pct: int | None = None
    me = next(p for p in obs.players if p.seat == obs.seat)
    call_cost = min(obs.to_call, me.stack)
    # A fórmula didática de MDF pressupõe que o defensor pode cobrir a aposta.
    # Um all-in curto muda o jogo/pote elegível; omitir é mais correto que exibir
    # um número com a aposta nominal que o jogador nem sequer pode pagar.
    if obs.to_call > 0 and obs.pot > 0 and call_cost == obs.to_call:
        mdf_pct = round((1 - call_cost / obs.pot) * 100)
    bluff_alpha_pct: int | None = None
    if action.type in (ActionType.RAISE, ActionType.ALL_IN):
        added = (action.amount - me.current_bet) if action.type == ActionType.RAISE else me.stack
        if added > 0 and added > obs.to_call:  # só quando a ação é de fato agressiva
            bluff_alpha_pct = round(added / (added + obs.pot) * 100)
    return mdf_pct, bluff_alpha_pct


def explain(
    name: str, level: str, obs: Observation, action: Action, insight: BotInsight | None
) -> ReasoningView:
    n_opp = max(obs.num_active - 1, 1)
    equity = estimate_equity(
        obs.hole,
        obs.board,
        n_opp,
        _EQUITY_SAMPLES,
        random.Random(20260704),  # noqa: S311 - deterministic explanation for the same state
    )
    me = next(p for p in obs.players if p.seat == obs.seat)
    call_cost = min(obs.to_call, me.stack)
    pot_odds = call_cost / (obs.pot + call_cost) if call_cost > 0 else 0.0
    eq, po = round(equity * 100), round(pot_odds * 100)
    mdf_pct, bluff_alpha_pct = _gto_numbers(obs, action)
    sig = round(insight.confidence * 100) if insight else None

    hand_label = _hand_name(obs.hole, obs.board)
    if hand_label is None:
        hand_label = _preflop_label(obs.hole)

    options = [
        _option(
            act,
            obs,
            eq,
            po,
            chosen=(act == action.type),
            amount=action.amount,
            equity_rate=equity,
            pot_odds_rate=pot_odds,
        )
        for act in _ORDER
        if act in obs.legal_actions
    ]
    past = _PAST.get(action.type, action.type.value)
    inf = _INF.get(action.type, action.type.value)

    return ReasoningView(
        seat=obs.seat,
        name=name,
        level=level,
        action=action.type.value,
        headline=f"{name} vai {_VERB.get(action.type, action.type.value)}",
        how_it_thinks=_pick(*_HOW.get(level, [""])),
        signal_label=(insight.label if insight else None),
        signal_value=(round(insight.confidence, 3) if insight else None),
        hand_label=hand_label,
        equity_pct=eq,
        pot=obs.pot,
        to_call=obs.to_call,
        pot_odds_pct=po,
        options=options,
        why_chosen=_why(level, name, past, inf, sig, eq, po, obs.to_call, insight),
        mdf_pct=mdf_pct,
        bluff_alpha_pct=bluff_alpha_pct,
    )
