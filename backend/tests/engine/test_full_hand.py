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


# ---- Tarefa 10: integração de mão completa ----

def _call_or_check(hand):
    """Estratégia trivial: paga se precisa, senão dá check (mão 'limpada')."""
    p = hand.players[hand.to_act]
    if p.current_bet < hand.current_bet:
        return Action(ActionType.CALL)
    return Action(ActionType.CHECK)


def test_chips_are_conserved_over_a_full_hand():
    players = _players()
    start_total = sum(p.stack for p in players)
    h = Hand(players, button=0, small_blind=10, big_blind=20, seed=99)
    h.start()
    winners = h.play_out(_call_or_check)
    assert sum(p.stack for p in h.players) == start_total  # nada some/aparece
    assert len(h.board) == 5  # foi até o river
    assert len(winners) >= 1

