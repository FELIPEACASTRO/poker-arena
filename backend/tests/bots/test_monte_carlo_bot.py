import random

from poker_arena.bots.monte_carlo_bot import MonteCarloBot, estimate_equity
from poker_arena.bots.observation import as_strategy, observation_for
from poker_arena.engine.evaluator import card_from_str
from poker_arena.engine.game import Hand
from poker_arena.engine.player import Player


def _players(n=6, stack=1000):
    return [Player(f"P{i}", stack) for i in range(n)]


def _c(s):
    return card_from_str(s)


def test_aces_have_high_preflop_equity_heads_up():
    eq = estimate_equity([_c("Ah"), _c("As")], [], num_opponents=1,
                         n_samples=800, rng=random.Random(1))
    assert eq > 0.75


def test_aces_beat_trash_in_equity():
    aces = estimate_equity([_c("Ah"), _c("As")], [], 1, 500, random.Random(3))
    trash = estimate_equity([_c("7d"), _c("2c")], [], 1, 500, random.Random(3))
    assert aces > trash


def test_made_nut_flush_has_high_equity():
    eq = estimate_equity([_c("Ah"), _c("Kh")],
                         [_c("Qh"), _c("7h"), _c("2h")], 1, 600, random.Random(4))
    assert eq > 0.8


def test_more_opponents_lower_equity():
    rng_a, rng_b = random.Random(5), random.Random(5)
    one = estimate_equity([_c("Ah"), _c("As")], [], 1, 500, rng_a)
    five = estimate_equity([_c("Ah"), _c("As")], [], 5, 500, rng_b)
    assert one > five  # AA vence menos vezes contra 5 do que contra 1


def test_monte_carlo_bot_returns_legal_action():
    h = Hand(_players(), button=0, small_blind=10, big_blind=20, seed=1)
    h.start()
    a = MonteCarloBot(seed=1, n_samples=100).act(observation_for(h))
    assert a.type in h.legal_actions()


def test_monte_carlo_bot_plays_full_hand_without_illegal():
    players = _players()
    total = sum(p.stack for p in players)
    h = Hand(players, button=0, small_blind=10, big_blind=20, seed=6)
    h.start()
    winners = h.play_out(as_strategy(MonteCarloBot(seed=3, n_samples=60)))
    assert sum(p.stack for p in h.players) == total
    assert len(winners) >= 1
