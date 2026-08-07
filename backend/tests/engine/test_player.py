import pytest

from poker_arena.engine.actions import Action, ActionType
from poker_arena.engine.player import Player, PlayerStatus


def test_player_starts_active_with_stack():
    p = Player(name="Bot1", stack=1000)
    assert p.stack == 1000
    assert p.status == PlayerStatus.ACTIVE
    assert p.current_bet == 0


def test_bet_reduces_stack_and_tracks_current_bet():
    p = Player(name="Bot1", stack=1000)
    p.bet(150)
    assert p.stack == 850
    assert p.current_bet == 150
    assert p.total_committed == 150


def test_betting_entire_stack_marks_all_in():
    p = Player(name="Bot1", stack=200)
    p.bet(200)
    assert p.stack == 0
    assert p.status == PlayerStatus.ALL_IN


def test_bet_caps_at_stack():
    p = Player(name="Bot1", stack=100)
    paid = p.bet(250)  # tenta apostar mais do que tem
    assert paid == 100
    assert p.stack == 0
    assert p.status == PlayerStatus.ALL_IN


def test_negative_bet_is_rejected_without_creating_chips():
    p = Player(name="Bot1", stack=100)
    with pytest.raises(ValueError):
        p.bet(-25)
    assert p.stack == 100
    assert p.current_bet == 0
    assert p.total_committed == 0


def test_reset_for_new_round_clears_current_bet():
    p = Player(name="Bot1", stack=1000)
    p.bet(150)
    p.acted = True
    p.reset_for_new_round()
    assert p.current_bet == 0
    assert p.acted is False
    assert p.total_committed == 150  # nao zera entre rodadas (p/ side pots)


def test_action_raise_carries_amount():
    a = Action(ActionType.RAISE, amount=300)
    assert a.type == ActionType.RAISE
    assert a.amount == 300
