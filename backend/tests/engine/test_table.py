from poker_arena.engine.actions import Action, ActionType
from poker_arena.engine.player import Player
from poker_arena.engine.table import Table


def _players(n=6, stack=1000):
    return [Player(f"P{i}", stack) for i in range(n)]


def _check_or_call(hand):
    legal = hand.legal_actions()
    if ActionType.CHECK in legal:
        return Action(ActionType.CHECK)
    return Action(ActionType.CALL)


def _shove(hand):
    legal = hand.legal_actions()
    if ActionType.ALL_IN in legal:
        return Action(ActionType.ALL_IN)
    return Action(ActionType.CALL)


def test_session_conserves_chips_over_many_hands():
    players = _players()
    total = sum(p.stack for p in players)
    table = Table(players, small_blind=10, big_blind=20, seed=7)
    for _ in range(30):
        if table.is_over():
            break
        table.play_hand(_check_or_call)
    assert sum(p.stack for p in players) == total
    assert table.hand_count >= 1


def test_button_rotates_each_hand():
    table = Table(_players(), small_blind=10, big_blind=20, seed=7)
    b0 = table.button
    table.play_hand(_check_or_call)
    assert table.button != b0


def test_button_moves_to_next_physical_survivor_after_elimination():
    players = [Player("A", 1000), Player("B", 1000), Player("C", 1000)]
    table = Table(players, small_blind=10, big_blind=20, seed=7)
    table.start_hand()  # a mão começou com A no botão e os três sentados
    players[0].stack = 0  # A era o botão e foi eliminado

    table.end_hand()
    hand = table.start_hand()

    assert hand.players[hand.button] is players[1]


def test_game_ends_with_a_single_winner_holding_all_chips():
    players = _players()
    total = sum(p.stack for p in players)
    table = Table(players, small_blind=10, big_blind=20, seed=3)
    winner = table.play_until_winner(_shove, max_hands=500)
    assert table.is_over()
    assert sum(p.stack for p in players) == total
    assert winner is not None
    assert winner.stack == total


def test_heads_up_button_posts_small_blind():
    # via Table, mas o efeito é da regra de heads-up no Hand
    from poker_arena.engine.game import Hand

    players = [Player("A", 1000), Player("B", 1000)]
    h = Hand(players, button=0, small_blind=10, big_blind=20, seed=1)
    h.start()
    assert players[0].current_bet == 10  # botão = small blind
    assert players[1].current_bet == 20  # BB
    assert h.to_act == 0  # SB/botão age primeiro no preflop
