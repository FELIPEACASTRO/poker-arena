"""Estratégia MISTA do Expert (anti-previsibilidade sem perder força).

Regras verificadas:
- piso: nunca sorteia ação com prob < ratio × favorita (não joga lixo);
- temperatura 0 = argmax (comportamento antigo é um caso particular);
- spots de alta certeza continuam determinísticos (só 1 ação sobrevive ao piso);
- spots equilibrados MISTURAM (mais de uma ação sai no longo prazo);
- jitter do aumento respeita os limites legais (min_raise_to..stack).
"""

import random
from collections import Counter

from poker_arena.bots.ml_bot import jitter_raise, sample_action
from poker_arena.bots.observation import Observation, PublicPlayer
from poker_arena.engine.actions import Action, ActionType
from poker_arena.engine.evaluator import card_from_str


def _rng(seed=1):
    return random.Random(seed)


# ---------- sample_action ----------
def test_temperature_zero_is_argmax():
    probs = [0.1, 0.5, 0.3, 0.05, 0.05]
    assert sample_action(probs, _rng(), temperature=0.0) == 1


def test_floor_excludes_clearly_worse_actions():
    # favorita 0.60; piso 15% -> 0.09: a ação de 0.05 NUNCA pode sair
    probs = [0.05, 0.60, 0.35, 0.0, 0.0]
    seen = {sample_action(probs, _rng(s)) for s in range(300)}
    assert 0 not in seen and 3 not in seen and 4 not in seen
    assert seen <= {1, 2}


def test_confident_spot_stays_deterministic():
    # rede com 99% de certeza: só a favorita sobrevive ao piso -> sempre ela
    probs = [0.99, 0.01, 0.0, 0.0, 0.0]
    seen = {sample_action(probs, _rng(s)) for s in range(200)}
    assert seen == {0}


def test_balanced_spot_mixes():
    # spot equilibrado (55/45): as DUAS ações precisam aparecer (estratégia mista)
    probs = [0.0, 0.55, 0.45, 0.0, 0.0]
    counts = Counter(sample_action(probs, _rng(s)) for s in range(400))
    assert set(counts) == {1, 2}
    assert counts[1] > counts[2]  # a favorita ainda sai mais (τ<1 afia)


def test_deterministic_given_seed():
    probs = [0.0, 0.5, 0.5, 0.0, 0.0]
    a = [sample_action(probs, _rng(7)) for _ in range(20)]
    b = [sample_action(probs, _rng(7)) for _ in range(20)]
    assert a == b  # reprodutível com o mesmo seed (testes/depuração)


# ---------- jitter_raise ----------
def _obs(min_raise_to=40, me_stack=1000, me_bet=0):
    me = PublicPlayer(
        seat=0, name="X", stack=me_stack, current_bet=me_bet,
        total_committed=me_bet, status="active", is_button=False,
    )
    return Observation(
        seat=0, hole=(card_from_str("Ah"), card_from_str("Kd")), board=(),
        pot=100, to_call=0, current_bet=me_bet, min_raise_to=min_raise_to,
        legal_actions=frozenset(), players=(me,), num_active=2,
    )


def test_jitter_respects_legal_bounds():
    obs = _obs(min_raise_to=40, me_stack=200)
    for s in range(200):
        a = jitter_raise(Action(ActionType.RAISE, 100), obs, _rng(s), jitter=0.5)
        assert 40 <= a.amount <= 200  # [min_raise_to, current_bet + stack]


def test_jitter_actually_varies_the_size():
    obs = _obs()
    sizes = {jitter_raise(Action(ActionType.RAISE, 100), obs, _rng(s)).amount for s in range(50)}
    assert len(sizes) > 5  # não é mais um número fixo


def test_jitter_leaves_non_raises_untouched():
    obs = _obs()
    for t in (ActionType.FOLD, ActionType.CHECK, ActionType.CALL, ActionType.ALL_IN):
        a = Action(t)
        assert jitter_raise(a, obs, _rng()) is a
