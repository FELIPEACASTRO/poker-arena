"""Avaliação por cross-play em **bb/100** — a métrica de força que de fato importa.

Mede quantas big blinds por 100 mãos uma política ganha contra bots de referência
FIXOS (random/heuristic/montecarlo). Positivo = a política vence. Substitui sinais
enganosos (concordância com solver, lucro vs si mesmo) pelo objetivo real: ganhar.
"""

from __future__ import annotations

import random
from collections.abc import Callable

from ..bots import HeuristicBot, MonteCarloBot, RandomBot
from ..bots.base import Bot
from ..bots.observation import Observation, observation_for
from ..engine.actions import Action
from ..engine.game import Hand
from ..engine.player import Player, PlayerStatus

HeroAct = Callable[[Observation], Action]

_MAX_HAND_TRANSITIONS = 500

_VILLAINS: dict[str, Callable[[int], Bot]] = {
    "random": lambda s: RandomBot(seed=s),
    "heuristic": lambda s: HeuristicBot(seed=s),
    "montecarlo": lambda s: MonteCarloBot(seed=s),
}


def _play_out(hand: Hand, hero_act: HeroAct, villains: list[Bot]) -> None:
    guard = 0
    while guard < _MAX_HAND_TRANSITIONS:
        guard += 1
        while not hand.round_complete():
            seat = hand.to_act
            obs = observation_for(hand)
            action = hero_act(obs) if seat == 0 else villains[seat - 1].act(obs)
            hand.apply(action)
        live = [p for p in hand.players if p.status != PlayerStatus.FOLDED]
        if len(live) <= 1 or len(hand.board) >= 5:
            hand.resolve()
            return
        hand.advance_street()
    raise RuntimeError(
        f"hand did not resolve within {_MAX_HAND_TRANSITIONS} betting/street transitions"
    )


def _villain_seeds(seed: int, n_villains: int) -> tuple[int, ...]:
    """Derive a panel-specific but reproducible RNG stream for the opponents."""

    rng = random.Random(seed ^ 0x5EED_5EED_5EED_5EED)  # noqa: S311 - reproducible simulation RNG
    return tuple(rng.randrange(1 << 63) for _ in range(n_villains))


def eval_bb100(
    hero_act: HeroAct,
    villain: str = "heuristic",
    *,
    hands: int = 1000,
    n: int = 6,
    stack: int = 1000,
    sb: int = 10,
    bb: int = 20,
    seed: int = 12345,
) -> float:
    """bb/100 do `hero_act` (assento 0) contra `villain` nos demais assentos.

    Determinístico por `seed`: comparável entre checkpoints. O herói deve usar a
    mesma regra declarada no manifesto (`modal` ou `sampled`) e os mesmos seeds;
    avaliar argmax e implantar amostragem mede políticas diferentes.
    """
    for name, value in (("hands", hands), ("n", n), ("stack", stack), ("sb", sb), ("bb", bb)):
        if type(value) is not int:
            raise TypeError(f"{name} must be an int")
    if type(seed) is not int:
        raise TypeError("seed must be an int")
    if hands <= 0:
        raise ValueError("hands must be positive")
    if n < 2:
        raise ValueError("n must be at least 2")
    if stack <= 0:
        raise ValueError("stack must be positive")
    if sb <= 0 or bb <= sb:
        raise ValueError("blinds must satisfy 0 < sb < bb")
    if bb > stack:
        raise ValueError("bb cannot exceed stack")
    if villain not in _VILLAINS:
        raise ValueError(f"unknown villain: {villain!r}")

    make = _VILLAINS[villain]
    villains = [make(villain_seed) for villain_seed in _villain_seeds(seed, n - 1)]
    rng = random.Random(seed)  # noqa: S311 - reproducible scientific evaluation RNG
    total = 0
    for h in range(hands):
        players = [Player(f"P{i}", stack) for i in range(n)]
        hand = Hand(
            players, button=h % n, small_blind=sb, big_blind=bb, seed=rng.randrange(1 << 30)
        )
        hand.start()
        _play_out(hand, hero_act, villains)
        total += players[0].stack - stack
    return total / hands / bb * 100.0
