from poker_arena.engine.actions import Action, ActionType
from poker_arena.engine.evaluator import card_from_str
from poker_arena.engine.game import Hand
from poker_arena.engine.player import Player, PlayerStatus

_BOARD = ["2c", "7d", "9s", "Jc", "4h"]  # sem par/flush/sequência no board


def _c(s):
    return card_from_str(s)


def _all_in(players, commits):
    for p, c in zip(players, commits, strict=True):
        p.total_committed = c
        p.status = PlayerStatus.ALL_IN


def test_three_way_all_in_builds_side_pots():
    players = [Player("A", 0), Player("B", 0), Player("C", 0)]
    _all_in(players, (100, 200, 300))
    h = Hand(players, button=0, small_blind=10, big_blind=20, seed=7)
    pots = h.build_side_pots()
    assert [pot.amount for pot in pots] == [300, 200]
    assert pots[0].eligible == players  # main: todos
    assert pots[1].eligible == [players[1], players[2]]  # side 1: B e C


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


def test_uncalled_refund_is_not_a_pot_or_a_winner():
    players = [Player("A", 300), Player("B", 490), Player("C", 0)]
    players[0].total_committed = 200
    players[1].total_committed = 10
    players[1].status = PlayerStatus.FOLDED
    players[2].total_committed = 50
    players[2].status = PlayerStatus.ALL_IN
    players[0].status = PlayerStatus.ALL_IN
    players[0].hole = [_c("2c"), _c("3d")]
    players[2].hole = [_c("Ah"), _c("Ad")]
    h = Hand(players, button=0, small_blind=10, big_blind=20, seed=7)
    h.board = [_c(s) for s in _BOARD]
    h.pot = 260

    assert [pot.amount for pot in h.build_side_pots()] == [30, 80]
    winners = h.resolve()

    assert winners == [players[2]]
    assert h.pot == 110
    assert [player.stack for player in players] == [450, 490, 110]


def test_split_pot_on_tie():
    players = [Player("A", 0), Player("B", 0)]
    _all_in(players, (100, 100))
    players[0].hole = [_c("Ah"), _c("Kd")]
    players[1].hole = [_c("As"), _c("Kc")]  # mesma mão -> empate
    h = Hand(players, button=0, small_blind=10, big_blind=20, seed=1)
    h.board = [_c(s) for s in _BOARD]
    winners = h.resolve()
    assert len(winners) == 2
    assert players[0].stack == 100
    assert players[1].stack == 100


def test_split_pot_odd_chip_goes_to_first():
    players = [Player("A", 0), Player("B", 0), Player("C", 0)]
    players[0].total_committed = 31
    players[0].status = PlayerStatus.FOLDED  # contribui mas não disputa
    _all_in([players[1], players[2]], (35, 35))
    players[1].hole = [_c("Ah"), _c("Kd")]
    players[2].hole = [_c("As"), _c("Kc")]  # empate entre B e C
    h = Hand(players, button=0, small_blind=10, big_blind=20, seed=1)
    h.board = [_c(s) for s in _BOARD]
    h.resolve()
    assert players[1].stack == 51  # recebe a ficha ímpar do main pot (93 -> 47)
    assert players[2].stack == 50
    assert sum(p.stack for p in players) == 101  # conservação


def test_multiple_odd_chips_are_distributed_clockwise_at_most_one_per_winner():
    players = [Player("A", 0), Player("B", 0), Player("C", 0), Player("Folded", 0)]
    _all_in(players[:3], (17, 17, 17))
    players[3].total_committed = 17
    players[3].status = PlayerStatus.FOLDED
    players[0].hole = [_c("2c"), _c("3d")]
    players[1].hole = [_c("4c"), _c("5d")]
    players[2].hole = [_c("6c"), _c("7d")]
    hand = Hand(players, button=3, small_blind=10, big_blind=20, seed=1)
    hand.board = [_c(s) for s in ["Ts", "Js", "Qs", "Ks", "As"]]

    hand.resolve()

    assert [player.stack for player in players] == [23, 23, 22, 0]


def test_all_in_preflop_runs_out_the_board():
    players = [Player(f"P{i}", 100) for i in range(3)]
    total = sum(p.stack for p in players)
    h = Hand(players, button=0, small_blind=10, big_blind=20, seed=5)
    h.start()

    def shove(hand):
        legal = hand.legal_actions()
        if ActionType.ALL_IN in legal:
            return Action(ActionType.ALL_IN)
        return Action(ActionType.CALL)

    winners = h.play_out(shove)
    assert len(h.board) == 5  # board foi completado para o showdown
    assert sum(p.stack for p in players) == total  # conservação
    assert len(winners) >= 1
