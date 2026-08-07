from poker_arena.bots.observation import observation_for
from poker_arena.engine.game import Hand
from poker_arena.engine.player import Player, PlayerStatus


def _hand():
    players = [Player(f"P{i}", 1000) for i in range(6)]
    h = Hand(players, button=0, small_blind=10, big_blind=20, seed=1)
    h.start()
    return h


def test_observation_exposes_only_own_hole_cards():
    h = _hand()
    seat = h.to_act
    obs = observation_for(h)
    assert tuple(obs.hole) == tuple(h.players[seat].hole)
    # SEGURANÇA por construção: nenhum jogador público carrega hole cards
    for pub in obs.players:
        assert not hasattr(pub, "hole")


def test_observation_carries_public_game_state():
    h = _hand()
    obs = observation_for(h)
    assert obs.seat == h.to_act
    assert tuple(obs.board) == tuple(h.board)
    assert obs.to_call == h.amount_to_call()
    assert obs.current_bet == h.current_bet
    assert obs.min_raise_to == h.min_raise_to()
    assert obs.legal_actions == h.legal_actions()
    assert len(obs.players) == 6
    assert obs.num_active == 6


def test_observation_counts_all_in_players_as_contesting():
    h = _hand()
    h.to_act = 0
    h.players[1].status = PlayerStatus.ALL_IN
    h.players[2].status = PlayerStatus.ALL_IN
    for p in h.players[3:]:
        p.status = PlayerStatus.FOLDED

    obs = observation_for(h)
    assert obs.num_active == 3
