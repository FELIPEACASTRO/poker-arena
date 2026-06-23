from poker_arena.engine.actions import Action, ActionType
from poker_arena.engine.game import Hand
from poker_arena.engine.player import Player


def _players(n=6, stack=1000):
    return [Player(f"P{i}", stack) for i in range(n)]


# ---- Tarefa 8: showdown / vencedor ----

def test_last_player_standing_wins_pot():
    h = Hand(_players(), button=0, small_blind=10, big_blind=20, seed=1)
    h.start()
    for _ in range(5):  # todos foldam menos um
        h.apply(Action(ActionType.FOLD))
    winners = h.resolve()
    assert len(winners) == 1
    assert winners[0].stack > 980  # recebeu o pote (blinds = 30)
