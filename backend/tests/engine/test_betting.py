from poker_arena.engine.actions import Action, ActionType
from poker_arena.engine.game import Hand
from poker_arena.engine.player import Player


def _players(n=6, stack=1000):
    return [Player(f"P{i}", stack) for i in range(n)]


# ---- Tarefa 5: início da mão ----

def test_blinds_are_posted():
    h = Hand(_players(), button=0, small_blind=10, big_blind=20, seed=1)
    h.start()
    assert h.players[1].current_bet == 10  # SB = esquerda do botão
    assert h.players[2].current_bet == 20  # BB
    assert h.pot == 30


def test_each_player_gets_two_hole_cards():
    h = Hand(_players(), button=0, small_blind=10, big_blind=20, seed=1)
    h.start()
    assert all(len(p.hole) == 2 for p in h.players)


def test_first_to_act_preflop_is_left_of_big_blind():
    h = Hand(_players(), button=0, small_blind=10, big_blind=20, seed=1)
    h.start()
    assert h.to_act == 3  # UTG, à esquerda do BB


# ---- Tarefa 6: rodada de aposta ----

def test_fold_marks_player():
    h = Hand(_players(), button=0, small_blind=10, big_blind=20, seed=1)
    h.start()
    actor = h.to_act
    h.apply(Action(ActionType.FOLD))
    assert h.players[actor].status.name == "FOLDED"


def test_call_matches_current_bet():
    h = Hand(_players(), button=0, small_blind=10, big_blind=20, seed=1)
    h.start()
    seat = h.to_act
    h.apply(Action(ActionType.CALL))
    assert h.players[seat].current_bet == 20  # igualou o BB


def test_round_completes_when_all_matched():
    h = Hand(_players(), button=0, small_blind=10, big_blind=20, seed=1)
    h.start()
    # UTG..button chamam, SB completa, BB dá check
    safety = 0
    while not h.round_complete() and safety < 12:
        seat = h.to_act
        if h.players[seat].current_bet == h.current_bet:
            h.apply(Action(ActionType.CHECK))
        else:
            h.apply(Action(ActionType.CALL))
        safety += 1
    assert h.round_complete()


# ---- Tarefa 7: progressão do board ----

def test_advance_to_flop_deals_three_cards():
    h = Hand(_players(), button=0, small_blind=10, big_blind=20, seed=1)
    h.start()
    safety = 0
    while not h.round_complete() and safety < 12:
        seat = h.to_act
        if h.players[seat].current_bet == h.current_bet:
            h.apply(Action(ActionType.CHECK))
        else:
            h.apply(Action(ActionType.CALL))
        safety += 1
    h.advance_street()
    assert len(h.board) == 3
    assert h.current_bet == 0
    assert all(p.current_bet == 0 for p in h.players)
