from poker_arena.bots.observation import as_strategy, observation_for
from poker_arena.bots.random_bot import RandomBot
from poker_arena.engine.game import Hand
from poker_arena.engine.player import Player


def _players(n=6, stack=1000):
    return [Player(f"P{i}", stack) for i in range(n)]


def test_random_bot_returns_a_legal_action():
    h = Hand(_players(), button=0, small_blind=10, big_blind=20, seed=1)
    h.start()
    action = RandomBot(seed=7).act(observation_for(h))
    assert action.type in h.legal_actions()


def test_random_bot_plays_a_full_hand_without_illegal_actions():
    players = _players()
    total = sum(p.stack for p in players)
    h = Hand(players, button=0, small_blind=10, big_blind=20, seed=3)
    h.start()
    winners = h.play_out(as_strategy(RandomBot(seed=11)))
    assert sum(p.stack for p in h.players) == total  # conservação de fichas
    assert len(winners) >= 1
