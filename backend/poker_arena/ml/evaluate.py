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

_VILLAINS: dict[str, Callable[[int], Bot]] = {
    "random": lambda s: RandomBot(seed=s),
    "heuristic": lambda s: HeuristicBot(seed=s),
    "montecarlo": lambda s: MonteCarloBot(seed=s),
}


def _play_out(hand: Hand, hero_act: HeroAct, villains: list[Bot]) -> None:
    guard = 0
    while guard < 500:
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
    MESMA decisão do deploy (argmax mascarado) pra a avaliação refletir o jogo real.
    """
    make = _VILLAINS[villain]
    villains = [make(200 + i) for i in range(n - 1)]
    rng = random.Random(seed)
    total = 0
    for h in range(hands):
        players = [Player(f"P{i}", stack) for i in range(n)]
        hand = Hand(players, button=h % n, small_blind=sb, big_blind=bb,
                    seed=rng.randrange(1 << 30))
        hand.start()
        _play_out(hand, hero_act, villains)
        total += players[0].stack - stack
    return total / hands / bb * 100.0
