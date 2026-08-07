from poker_arena.bots.heuristic_bot import HeuristicBot, preflop_strength
from poker_arena.bots.observation import as_strategy, observation_for
from poker_arena.engine.evaluator import card_from_str
from poker_arena.engine.game import Hand
from poker_arena.engine.player import Player


def _players(n=6, stack=1000):
    return [Player(f"P{i}", stack) for i in range(n)]


def _c(s):
    return card_from_str(s)


def test_heuristic_bot_returns_legal_action():
    h = Hand(_players(), button=0, small_blind=10, big_blind=20, seed=1)
    h.start()
    a = HeuristicBot(seed=1).act(observation_for(h))
    assert a.type in h.legal_actions()


def test_heuristic_bot_plays_full_hand_without_illegal():
    players = _players()
    total = sum(p.stack for p in players)
    h = Hand(players, button=0, small_blind=10, big_blind=20, seed=4)
    h.start()
    winners = h.play_out(as_strategy(HeuristicBot(seed=2)))
    assert sum(p.stack for p in h.players) == total
    assert len(winners) >= 1


def test_preflop_strength_orders_hands_sensibly():
    aces = [_c("Ah"), _c("As")]
    trash = [_c("7d"), _c("2c")]
    assert preflop_strength(aces) > preflop_strength(trash)
    assert preflop_strength(aces) > 0.8
    assert preflop_strength(trash) < 0.5
