"""Differential conformance tests against the independent PokerKit engine."""

from __future__ import annotations

import pytest

pytest.importorskip("pokerkit")
from pokerkit import StandardHighHand  # noqa: E402

from poker_arena.engine.actions import Action, ActionType  # noqa: E402
from poker_arena.engine.evaluator import card_from_str, compare  # noqa: E402
from poker_arena.engine.game import IllegalActionError  # noqa: E402
from tests.helpers.pokerkit_oracle import (  # noqa: E402
    DealPlan,
    DifferentialState,
    all_in,
    check_or_call,
    fold,
    play_differential_hand,
    raise_to,
)


def _cards(compact: str):
    return [card_from_str(compact[index : index + 2]) for index in range(0, len(compact), 2)]


@pytest.mark.parametrize(
    ("hole_a", "hole_b", "board"),
    [
        ("JhTh", "AdAc", "AhKhQh2c3d"),  # royal flush beats three aces
        ("As5d", "9h9c", "2c3d4hKsQd"),  # wheel straight beats a pair
        ("KhKd", "QhQd", "2h7d9sJc4h"),  # higher pair
        ("AhKd", "AsKc", "2h7d9sJc4h"),  # exact tie
        ("2c3d", "AhAd", "TsJsQsKsAs"),  # board plays: royal-flush tie
    ],
)
def test_hand_order_and_ties_match_pokerkit(hole_a: str, hole_b: str, board: str):
    internal = compare(_cards(hole_a), _cards(hole_b), _cards(board))
    oracle_a = StandardHighHand.from_game(hole_a, board)
    oracle_b = StandardHighHand.from_game(hole_b, board)
    pokerkit_order = (oracle_a > oracle_b) - (oracle_a < oracle_b)

    assert internal == pokerkit_order


@pytest.mark.parametrize("button", [0, 1])
def test_heads_up_blinds_and_first_actor_match_pokerkit(button: int):
    pair = DifferentialState([100, 100], button=button)

    assert tuple(player.current_bet for player in pair.players) == pair.pokerkit_bets
    assert tuple(player.stack for player in pair.players) == pair.pokerkit_stacks
    assert pair.internal.to_act == pair.pokerkit_actor == button
    assert pair.players[button].current_bet == 10
    assert pair.players[(button + 1) % 2].current_bet == 20


@pytest.mark.parametrize("button", [0, 1, 2, 3])
def test_action_order_and_stacks_match_for_every_button_rotation(button: int):
    # Four preflop actions followed by four checks on each postflop street.
    script = [check_or_call() for _ in range(16)]
    result = play_differential_hand([1000, 1000, 1000, 1000], script, button=button, seed=42)
    preflop_order = tuple((button + offset) % 4 for offset in (3, 0, 1, 2))
    postflop_order = tuple((button + offset) % 4 for offset in (1, 2, 3, 0))

    assert result.actor_trace[:4] == preflop_order
    assert result.actor_trace[4:] == postflop_order * 3
    assert result.internal_stacks == result.pokerkit_stacks


def test_multiway_all_in_side_pots_and_winners_match_pokerkit():
    deal = DealPlan(
        holes=("QhQd", "AhAd", "ThTd", "KhKd"),
        board="2c7c9s5s4h",
        burns=("3h", "6h", "8h"),
    )
    result = play_differential_hand(
        [500, 200, 1000, 350],
        [raise_to(100), all_in(), all_in(), all_in(), check_or_call()],
        button=3,
        seed=11,
        deal=deal,
    )

    assert result.pot_amounts == (800, 450, 300)
    assert result.board == ("2c", "7c", "9s", "5s", "4h")
    assert result.internal_stacks == result.pokerkit_stacks == (300, 800, 500, 450)


def test_split_pot_and_odd_chip_position_match_pokerkit():
    deal = DealPlan(
        holes=("2c3d", "4c5d", "6c7d"),
        board="TsJsQsKsAs",
        burns=("2h", "3h", "4h"),
    )
    script = [
        check_or_call(),
        check_or_call(),
        check_or_call(),
        check_or_call(),
        check_or_call(),
        raise_to(21),
        check_or_call(),
        check_or_call(),
        check_or_call(),
        raise_to(20),
        fold(),
        check_or_call(),
        check_or_call(),
        check_or_call(),
    ]
    result = play_differential_hand([1000, 1000, 1000], script, button=2, seed=1, deal=deal)

    assert result.pot_amounts == (123, 40)
    assert result.internal_stacks == result.pokerkit_stacks == (1021, 1020, 959)


def test_single_short_all_in_does_not_reopen_raising_in_either_engine():
    pair = DifferentialState([80, 1000, 1000], button=2)
    pair.apply(raise_to(60))
    pair.apply(all_in())
    pair.apply(check_or_call())

    assert pair.internal.to_act == pair.pokerkit_actor == 2
    assert ActionType.RAISE not in pair.internal.legal_actions()
    assert not pair.pokerkit.can_complete_bet_or_raise_to()


def test_cumulative_short_all_ins_reopen_raising_in_either_engine():
    pair = DifferentialState([180, 1000, 1000, 140], button=3)
    pair.apply(raise_to(100))
    pair.apply(all_in())
    pair.apply(all_in())
    pair.apply(check_or_call())

    assert pair.internal.to_act == pair.pokerkit_actor == 2
    assert pair.internal.min_raise_to() == pair.pokerkit.min_completion_betting_or_raising_to_amount
    assert ActionType.RAISE in pair.internal.legal_actions()
    assert pair.pokerkit.can_complete_bet_or_raise_to()


def test_below_minimum_non_all_in_raise_is_rejected_by_both_engines():
    pair = DifferentialState([1000, 1000, 1000], button=2)

    assert pair.internal.min_raise_to() == pair.pokerkit.min_completion_betting_or_raising_to_amount
    assert not pair.pokerkit.can_complete_bet_or_raise_to(30)
    with pytest.raises(IllegalActionError):
        pair.internal.apply(Action(ActionType.RAISE, amount=30))
    with pytest.raises(ValueError):
        pair.pokerkit.complete_bet_or_raise_to(30)
