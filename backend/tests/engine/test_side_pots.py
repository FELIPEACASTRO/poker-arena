from poker_arena.engine.evaluator import card_from_str
from poker_arena.engine.game import Hand
from poker_arena.engine.player import Player, PlayerStatus


def _c(s):
    return card_from_str(s)


def _all_in(players, commits):
    for p, c in zip(players, commits):
        p.total_committed = c
        p.status = PlayerStatus.ALL_IN


def test_three_way_all_in_builds_side_pots():
    players = [Player("A", 0), Player("B", 0), Player("C", 0)]
    _all_in(players, (100, 200, 300))
    h = Hand(players, button=0, small_blind=10, big_blind=20, seed=7)
    pots = h.build_side_pots()
    assert [pot.amount for pot in pots] == [300, 200, 100]
    assert pots[0].eligible == players                  # main: todos
    assert pots[1].eligible == [players[1], players[2]]  # side 1: B e C
    assert pots[2].eligible == [players[2]]              # side 2: só C


def test_side_pot_resolution_awards_by_best_hand():
    players = [Player("A", 0), Player("B", 0), Player("C", 0)]
    _all_in(players, (100, 200, 300))
    players[0].hole = [_c("Ah"), _c("Ad")]  # par de ases (melhor)
    players[1].hole = [_c("Kh"), _c("Kd")]  # par de reis
    players[2].hole = [_c("Qh"), _c("Qd")]  # par de damas
    h = Hand(players, button=0, small_blind=10, big_blind=20, seed=7)
    h.board = [_c("2c"), _c("7d"), _c("9s"), _c("Jc"), _c("4h")]
    h.resolve()
    assert players[0].stack == 300  # A (ases) ganha só o main pot
    assert players[1].stack == 200  # B (reis) ganha o side pot 1
    assert players[2].stack == 100  # C recebe de volta o side pot 2
    assert sum(p.stack for p in players) == 600  # conservação de fichas
