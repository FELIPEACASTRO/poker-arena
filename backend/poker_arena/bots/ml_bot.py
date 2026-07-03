"""MLBot — nível 🔴 Expert por IA treinada (política neural via ONNX).

Carrega a política exportada do treino (notebook 05: warm-start no solver +
self-play) e joga implementando o protocolo `Bot`. O fluxo é a ACL ao contrário:
`encode(obs)` → ONNX → logits das 5 ações → máscara legal → **ESTRATÉGIA MISTA**:
sorteia a ação da própria distribuição da rede (com temperatura + piso), como os
profissionais e o Pluribus — em vez de sempre jogar o argmax.

Por que misto e não argmax? O equilíbrio do poker (GTO) é uma estratégia MISTA:
quem joga sempre a mesma ação no mesmo spot é previsível e explorável. O piso de
probabilidade garante que só se sorteia entre jogadas que a própria rede considera
próximas — onde ela tem certeza (ex.: 99%), o comportamento continua o do argmax.

onnxruntime/numpy entram só aqui (import dentro do __init__): o resto do backend
não depende deles a menos que o Expert seja usado.
"""

from __future__ import annotations

import random
from pathlib import Path

from ..engine.actions import Action, ActionType
from ..engine.cards import make_rng
from ..ml.encoder import ACTIONS, N_ACTIONS, encode, legal_mask, to_action
from .insight import BotInsight
from .observation import Observation

# rótulos curtos das 5 ações discretas (pro glass-box)
_PT = {
    "fold": "desistir",
    "check_call": "pagar",
    "raise_half": "aumentar ½",
    "raise_pot": "aumentar pote",
    "all_in": "all-in",
}

# estratégia mista (defaults calibrados; ver benchmark no commit)
TEMPERATURE = 0.75  # <1 afia a distribuição -> preserva a força
MIN_PROB_RATIO = 0.15  # descarta ações com prob < 15% da favorita (nunca joga lixo)
SIZING_JITTER = 0.12  # ±12% no tamanho do aumento (tira o padrão "de máquina")

# guarda de equity (busca-lite) — EXPERIMENTO MEDIDO E REPROVADO (fica OFF).
#
# A análise devastadora mediu over-fold (70-78% das apostas) e sangria de blinds
# (~17 bb/100). Hipótese: vetar folds quando a equity simulada supera o preço.
# Resultado do benchmark pareado (mesmos baralhos, ON vs OFF):
#   - versão ampla:    -357 bb/100 no agregado (all-in multiway: equity vs mão
#     aleatória superestima; a variância come o ganho);
#   - versão restrita (defesa barata de pote pequeno): -84 no agregado — paga o
#     pré-flop barato mas a POLÍTICA folda depois no flop ("call sem plano").
# Conclusão: a política treinada é coerente (tight-premium + pós-flop dela);
# remendo de inferência não a melhora. O caminho real é RETREINAR (notebook 06)
# com pool de oponentes diverso e features de histórico. O código fica como
# experimento documentado/testado, desligado por padrão.
GUARD_SAMPLES = 120  # simulações de equity (só roda quando a política foldaria)
GUARD_MARGIN = 0.10  # folga mínima de equity sobre o preço pra vetar o fold
GUARD_MAX_PRICE = 0.30  # só defesas baratas (pot odds até 30%)
GUARD_MAX_STACK_FRAC = 0.10  # e que custem no máx. 10% do stack (sem potes gigantes)


def should_defend(equity: float, price: float, to_call: int, stack: int) -> bool:
    """Fold dominado? Só em defesa barata de pote pequeno, com folga de equity."""
    if price > GUARD_MAX_PRICE or to_call > GUARD_MAX_STACK_FRAC * stack:
        return False
    return equity >= price + GUARD_MARGIN


def sample_action(
    probs: list[float],
    rng: random.Random,
    temperature: float = TEMPERATURE,
    min_prob_ratio: float = MIN_PROB_RATIO,
) -> int:
    """Sorteia um índice da distribuição (estratégia mista), com salvaguardas.

    - Piso: só participam ações com prob >= `min_prob_ratio` × prob da favorita —
      nunca se sorteia uma jogada que a rede considera claramente pior.
    - Temperatura: pesos = p^(1/τ); τ<1 concentra na favorita (τ→0 = argmax).
    """
    top = max(probs)
    if top <= 0.0:
        return probs.index(top)
    kept = [(i, p) for i, p in enumerate(probs) if p > 0.0 and p >= min_prob_ratio * top]
    if temperature <= 0.0 or len(kept) == 1:
        return max(kept, key=lambda x: x[1])[0]
    weights = [(i, p ** (1.0 / temperature)) for i, p in kept]
    total = sum(w for _, w in weights)
    r = rng.random() * total
    acc = 0.0
    for i, w in weights:
        acc += w
        if r <= acc:
            return i
    return weights[-1][0]


def jitter_raise(action: Action, obs: Observation, rng: random.Random,
                 jitter: float = SIZING_JITTER) -> Action:
    """Varia o TAMANHO do aumento em ±jitter, dentro dos limites legais.

    Tamanhos sempre exatos (½ pote / pote) entregam o padrão pra um humano; um
    ruído pequeno não muda o EV de forma relevante e apaga a assinatura.
    """
    if action.type is not ActionType.RAISE or jitter <= 0.0:
        return action
    me = next(p for p in obs.players if p.seat == obs.seat)
    max_to = me.current_bet + me.stack
    scaled = round(action.amount * (1.0 + rng.uniform(-jitter, jitter)))
    return Action(ActionType.RAISE, max(obs.min_raise_to, min(scaled, max_to)))


class MLBot:
    def __init__(
        self,
        model_path: str | Path,
        name: str = "Rex (Expert)",
        *,
        temperature: float = TEMPERATURE,
        min_prob_ratio: float = MIN_PROB_RATIO,
        sizing_jitter: float = SIZING_JITTER,
        equity_guard: bool = False,  # experimento reprovado na medição (ver acima)
        seed: int | None = None,
    ):
        import numpy as np
        import onnxruntime as ort

        self.name = name
        self._np = np
        self._session = ort.InferenceSession(
            str(model_path), providers=["CPUExecutionProvider"]
        )
        self._input = self._session.get_inputs()[0].name
        self._last_insight: BotInsight | None = None
        self._temperature = temperature
        self._min_prob_ratio = min_prob_ratio
        self._sizing_jitter = sizing_jitter
        self._equity_guard = equity_guard
        self._rng = make_rng(seed)  # cripto em produção; reprodutível com seed

    def _softmax_legal(self, logits: list[float], obs: Observation) -> list[float]:
        """Distribuição da rede SÓ sobre as ações legais (ilegais ≈ 0)."""
        mask = legal_mask(obs)
        masked = self._np.array(
            [logits[i] if mask[i] else -self._np.inf for i in range(N_ACTIONS)],
            dtype="float64",
        )
        masked -= masked.max()
        exps = self._np.exp(masked)  # exp(-inf) = 0
        return (exps / exps.sum()).tolist()

    def _guarded_fold(self, obs: Observation) -> tuple[bool, str]:
        """Veta um fold dominado: defesa barata de pote pequeno com equity de sobra."""
        me = next(p for p in obs.players if p.seat == obs.seat)
        price = obs.to_call / (obs.pot + obs.to_call)
        # pré-filtro barato ANTES de simular (fora do escopo, nem gasta equity)
        if price > GUARD_MAX_PRICE or obs.to_call > GUARD_MAX_STACK_FRAC * max(me.stack, 1):
            return False, ""
        from .monte_carlo_bot import estimate_equity  # lazy: reusa o motor de equity

        n_opp = max(
            sum(1 for p in obs.players if p.status == "active" and p.seat != obs.seat), 1
        )
        equity = estimate_equity(obs.hole, obs.board, n_opp, GUARD_SAMPLES, self._rng)
        if should_defend(equity, price, obs.to_call, me.stack):
            note = (
                f" · veto matemático: equity {round(equity * 100)}% ≫ preço "
                f"{round(price * 100)}% → paga em vez de desistir"
            )
            return True, note
        return False, ""

    def act(self, obs: Observation) -> Action:
        feats = self._np.asarray([encode(obs)], dtype=self._np.float32)
        logits = self._session.run(None, {self._input: feats})[0][0].tolist()
        probs = self._softmax_legal(logits, obs)
        top = max(range(N_ACTIONS), key=lambda i: probs[i])
        chosen = sample_action(
            probs, self._rng, self._temperature, self._min_prob_ratio
        )
        guard_note = ""
        # guarda anti-over-fold: só quando a política quer DESISTIR diante de aposta
        if self._equity_guard and chosen == 0 and obs.to_call > 0 and legal_mask(obs)[1]:
            defend, guard_note = self._guarded_fold(obs)
            if defend:
                chosen = 1  # check_call
        if chosen == top:
            label = f"Rede neural: {_PT[ACTIONS[top]]} ({round(probs[top] * 100)}%)"
        elif guard_note:
            label = f"Rede neural: queria {_PT[ACTIONS[top]]}{guard_note}"
        else:  # estratégia mista em ação — o glass-box mostra o sorteio
            label = (
                f"Rede neural (mista): sorteou {_PT[ACTIONS[chosen]]} "
                f"({round(probs[chosen] * 100)}%); favorita {_PT[ACTIONS[top]]} "
                f"({round(probs[top] * 100)}%)"
            )
        self._last_insight = BotInsight(
            kind="expert",
            label=label,
            confidence=probs[chosen],
            probs=tuple(probs),
        )
        return jitter_raise(to_action(obs, chosen), obs, self._rng, self._sizing_jitter)

    def insight(self) -> BotInsight | None:
        return self._last_insight
