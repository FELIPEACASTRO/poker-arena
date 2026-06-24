from poker_arena.bots.observation import Observation, PublicPlayer, observation_for
from poker_arena.engine.actions import ActionType
from poker_arena.engine.cards import Card, Rank, Suit
from poker_arena.engine.game import Hand
from poker_arena.engine.player import Player
from poker_arena.ml.encoder import (
    FEATURE_SIZE,
    encode,
    legal_mask,
    to_action,
)

_STRENGTH_IDX = 110  # último escalar: 52 (hole) + 52 (board) + 6 escalares anteriores


def _obs():
    players = [Player(f"P{i}", 1000) for i in range(6)]
    h = Hand(players, button=0, small_blind=10, big_blind=20, seed=1)
    h.start()
    return h, observation_for(h)


def _obs_with_hole(hole: tuple[Card, ...]) -> Observation:
    players = (
        PublicPlayer(0, "me", 1000, 0, 0, "active", True),
        PublicPlayer(1, "x", 1000, 0, 0, "active", False),
    )
    return Observation(
        seat=0, hole=hole, board=(), pot=0, to_call=0, current_bet=0, min_raise_to=20,
        legal_actions=frozenset({ActionType.CHECK, ActionType.RAISE}),
        players=players, num_active=2,
    )


def test_feature_vector_has_fixed_size():
    _, obs = _obs()
    v = encode(obs)
    assert len(v) == FEATURE_SIZE == 121
    assert all(isinstance(x, float) for x in v)


def test_hand_strength_feature_ranks_hands():
    aa = encode(_obs_with_hole((Card(Rank.ACE, Suit.SPADES), Card(Rank.ACE, Suit.HEARTS))))
    weak = encode(_obs_with_hole((Card(Rank.SEVEN, Suit.SPADES), Card(Rank.TWO, Suit.HEARTS))))
    assert 0.0 <= aa[_STRENGTH_IDX] <= 1.0
    assert aa[_STRENGTH_IDX] > weak[_STRENGTH_IDX]  # AA mais forte que 72o


def test_hole_cards_are_encoded():
    _, obs = _obs()
    v = encode(obs)
    assert sum(v[:52]) == 2.0  # exatamente as 2 cartas próprias
    assert sum(v[52:104]) == len(obs.board)  # board (vazio no preflop)


def test_legal_mask_preflop_utg():
    _, obs = _obs()
    mask = legal_mask(obs)
    # UTG enfrentando o BB: fold/call/raise/all-in legais; check NÃO
    assert mask[0] is True  # fold
    assert mask[1] is True  # check_call -> call
    assert mask[2] is True  # raise_half
    assert mask[3] is True  # raise_pot
    assert mask[4] is True  # all_in


def test_to_action_is_legal_for_every_unmasked_index():
    h, obs = _obs()
    mask = legal_mask(obs)
    for i, ok in enumerate(mask):
        if ok:
            assert to_action(obs, i).type in h.legal_actions()


def test_raise_actions_respect_min_and_max():
    h, obs = _obs()
    me = next(p for p in obs.players if p.seat == obs.seat)
    for i in (2, 3):  # raise_half, raise_pot
        a = to_action(obs, i)
        assert obs.min_raise_to <= a.amount <= me.current_bet + me.stack
