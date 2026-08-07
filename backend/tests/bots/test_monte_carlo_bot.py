import random

import pytest

from poker_arena.bots.monte_carlo_bot import (
    MonteCarloBot,
    estimate_equity,
    estimate_equity_with_uncertainty,
)
from poker_arena.bots.observation import as_strategy, observation_for
from poker_arena.engine.evaluator import card_from_str
from poker_arena.engine.game import Hand
from poker_arena.engine.player import Player


def _players(n=6, stack=1000):
    return [Player(f"P{i}", stack) for i in range(n)]


def _c(s):
    return card_from_str(s)


def test_aces_have_high_preflop_equity_heads_up():
    eq = estimate_equity(
        [_c("Ah"), _c("As")], [], num_opponents=1, n_samples=800, rng=random.Random(1)
    )
    assert eq > 0.75


def test_aces_beat_trash_in_equity():
    aces = estimate_equity([_c("Ah"), _c("As")], [], 1, 500, random.Random(3))
    trash = estimate_equity([_c("7d"), _c("2c")], [], 1, 500, random.Random(3))
    assert aces > trash


def test_made_nut_flush_has_high_equity():
    eq = estimate_equity(
        [_c("Ah"), _c("Kh")], [_c("Qh"), _c("7h"), _c("2h")], 1, 600, random.Random(4)
    )
    assert eq > 0.8


def test_more_opponents_lower_equity():
    rng_a, rng_b = random.Random(5), random.Random(5)
    one = estimate_equity([_c("Ah"), _c("As")], [], 1, 500, rng_a)
    five = estimate_equity([_c("Ah"), _c("As")], [], 5, 500, rng_b)
    assert one > five  # AA vence menos vezes contra 5 do que contra 1


def test_three_way_board_tie_splits_equity_three_ways():
    board = [_c("As"), _c("Ks"), _c("Qs"), _c("Js"), _c("Ts")]
    eq = estimate_equity(
        [_c("2h"), _c("3d")],
        board,
        num_opponents=2,
        n_samples=1,
        rng=random.Random(9),
    )
    assert eq == 1 / 3


def test_heads_up_river_is_exact_and_independent_of_sampling_budget():
    hole = [_c("As"), _c("Kh")]
    board = [_c("2c"), _c("7d"), _c("Jh"), _c("9s"), _c("3c")]

    first = estimate_equity_with_uncertainty(hole, board, 1, 1, random.Random(1))
    second = estimate_equity_with_uncertainty(hole, board, 1, 10_000, random.Random(999))

    assert first == second
    assert first.method == "exact-river-heads-up"
    assert first.trials == 990
    assert first.standard_error == 0.0
    assert first.equity == pytest.approx(0.37626262626262624)
    assert first.ci95_lower == first.ci95_upper == first.equity


def test_sampled_equity_discloses_sampling_uncertainty():
    estimate = estimate_equity_with_uncertainty(
        [_c("As"), _c("Kh")],
        [_c("2c"), _c("7d"), _c("Jh")],
        2,
        5_000,
        random.Random(42),
    )

    assert estimate.method == "monte-carlo-uniform-range"
    assert estimate.trials == 5_000
    assert 0.0 < estimate.standard_error < 0.02
    assert estimate.ci95_lower < estimate.equity < estimate.ci95_upper


def test_sampled_edge_equity_does_not_claim_zero_uncertainty():
    estimate = estimate_equity_with_uncertainty(
        [_c("As"), _c("Ks")],
        [_c("Qs"), _c("Js"), _c("Ts")],
        1,
        20,
        random.Random(1),
        exact_when_possible=False,
    )

    assert estimate.equity == 1.0
    assert estimate.standard_error > 0
    assert estimate.ci95_lower < 1.0
    assert estimate.ci95_upper == 1.0


def test_equity_rejects_duplicate_or_incomplete_card_state():
    with pytest.raises(ValueError, match="repetidas"):
        estimate_equity([_c("As"), _c("As")], [], 1, 10, random.Random(1))
    with pytest.raises(ValueError, match="exatamente duas"):
        estimate_equity([_c("As")], [], 1, 10, random.Random(1))


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
