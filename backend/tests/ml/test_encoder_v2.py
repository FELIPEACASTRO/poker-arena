from __future__ import annotations

from dataclasses import replace

import pytest

from poker_arena.bots.observation import Observation, PublicPlayer, observation_for
from poker_arena.engine.actions import Action, ActionType
from poker_arena.engine.cards import Card, Rank, Suit
from poker_arena.engine.game import Hand, PublicActionEvent
from poker_arena.engine.player import Player
from poker_arena.ml.encoder_v2 import (
    CARD_FEATURES,
    GLOBAL_FEATURES,
    HISTORY_FEATURES,
    MAX_HISTORY,
    MAX_SEATS,
    SEAT_FEATURES,
    encode_v2,
)


def _observation() -> Observation:
    hand = Hand([Player(f"P{index}", 1_000) for index in range(6)], 0, 10, 20, seed=7)
    hand.start()
    hand.apply(Action(ActionType.CALL))
    return observation_for(hand)


def _remap(card: Card, mapping: dict[Suit, Suit]) -> Card:
    return Card(card.rank, mapping[card.suit])


def test_encoder_v2_shapes_are_exact_and_history_is_real():
    encoded = encode_v2(_observation())
    assert len(encoded.cards) == CARD_FEATURES == 208
    assert len(encoded.global_features) == GLOBAL_FEATURES == 24
    assert len(encoded.seats) == MAX_SEATS == 9
    assert all(len(row) == SEAT_FEATURES == 12 for row in encoded.seats)
    assert len(encoded.history) == len(encoded.history_mask) == MAX_HISTORY == 15
    assert all(len(row) == HISTORY_FEATURES == 26 for row in encoded.history)
    assert sum(encoded.history_mask) == 3.0  # SB, BB e call
    assert len(encoded.legal_mask) == 10


def test_global_suit_permutation_produces_identical_card_tensor():
    base = _observation()
    mapping = {
        Suit.SPADES: Suit.HEARTS,
        Suit.HEARTS: Suit.DIAMONDS,
        Suit.DIAMONDS: Suit.CLUBS,
        Suit.CLUBS: Suit.SPADES,
    }
    permuted = replace(
        base,
        hole=tuple(_remap(card, mapping) for card in base.hole),
        board=tuple(_remap(card, mapping) for card in base.board),
    )
    assert encode_v2(base).cards == encode_v2(permuted).cards


def test_hole_and_flop_order_do_not_change_encoding():
    base = Observation(
        seat=0,
        hole=(Card(Rank.ACE, Suit.SPADES), Card(Rank.KING, Suit.HEARTS)),
        board=(
            Card(Rank.TWO, Suit.CLUBS),
            Card(Rank.SEVEN, Suit.DIAMONDS),
            Card(Rank.JACK, Suit.SPADES),
        ),
        pot=100,
        to_call=0,
        current_bet=0,
        min_raise_to=20,
        legal_actions=frozenset({ActionType.CHECK, ActionType.RAISE, ActionType.ALL_IN}),
        players=(
            PublicPlayer(0, "hero", 900, 0, 100, "active", True),
            PublicPlayer(1, "villain", 900, 0, 100, "active", False),
        ),
        num_active=2,
    )
    permuted = replace(base, hole=tuple(reversed(base.hole)), board=tuple(reversed(base.board)))
    assert encode_v2(base).cards == encode_v2(permuted).cards


def test_turn_and_river_identity_are_not_collapsed_into_an_unordered_board():
    base = Observation(
        seat=0,
        hole=(Card(Rank.ACE, Suit.SPADES), Card(Rank.KING, Suit.HEARTS)),
        board=(
            Card(Rank.TWO, Suit.CLUBS),
            Card(Rank.SEVEN, Suit.DIAMONDS),
            Card(Rank.JACK, Suit.SPADES),
            Card(Rank.THREE, Suit.HEARTS),
            Card(Rank.FOUR, Suit.CLUBS),
        ),
        pot=100,
        to_call=0,
        current_bet=0,
        min_raise_to=20,
        legal_actions=frozenset({ActionType.CHECK, ActionType.RAISE, ActionType.ALL_IN}),
        players=(
            PublicPlayer(0, "hero", 900, 0, 100, "active", True),
            PublicPlayer(1, "villain", 900, 0, 100, "active", False),
        ),
        num_active=2,
    )
    swapped_streets = replace(
        base,
        board=(*base.board[:3], base.board[4], base.board[3]),
    )

    assert encode_v2(base).cards != encode_v2(swapped_streets).cards


def test_per_seat_stack_information_is_not_collapsed():
    base = _observation()
    players = list(base.players)
    first, second = players[1], players[2]
    players[1] = replace(first, stack=first.stack - 400)
    players[2] = replace(second, stack=second.stack + 400)
    changed = replace(base, players=tuple(players))
    assert encode_v2(base).seats != encode_v2(changed).seats


def test_normalization_scale_uses_conserved_chips_not_approximate_reported_pot():
    base = Observation(
        seat=0,
        hole=(Card(Rank.ACE, Suit.SPADES), Card(Rank.KING, Suit.HEARTS)),
        board=(),
        pot=100,
        to_call=20,
        current_bet=40,
        min_raise_to=60,
        legal_actions=frozenset({ActionType.FOLD, ActionType.CALL, ActionType.RAISE}),
        players=(
            PublicPlayer(0, "hero", 900, 20, 100, "active", True),
            PublicPlayer(1, "villain", 900, 40, 100, "active", False),
        ),
        num_active=2,
    )
    changed_reported_pot = replace(base, pot=120)

    original = encode_v2(base).global_features
    changed = encode_v2(changed_reported_pot).global_features

    # Only the three features whose definitions intentionally depend on the
    # reported pot may move: normalized pot, effective-stack-to-pot and odds.
    pot_sensitive = {0, 9, 10}
    assert all(original[index] != changed[index] for index in pot_sensitive)
    assert all(
        original[index] == changed[index]
        for index in range(GLOBAL_FEATURES)
        if index not in pot_sensitive
    )


def test_encoder_v2_rejects_invalid_numeric_type_before_inference():
    base = _observation()
    with pytest.raises(ValueError, match="pot must be a non-negative int"):
        encode_v2(replace(base, pot=True))
    with pytest.raises(ValueError, match="pot must be a non-negative int"):
        encode_v2(replace(base, pot=-1))
    players = list(base.players)
    players[0] = replace(players[0], stack=float("nan"))
    with pytest.raises(ValueError, match="player.stack must be a non-negative int"):
        encode_v2(replace(base, players=tuple(players)))


def test_encoder_v2_rejects_semantically_invalid_public_state():
    base = _observation()
    players = list(base.players)
    players[1] = replace(players[1], is_button=True)
    with pytest.raises(ValueError, match="exactly one button"):
        encode_v2(replace(base, players=tuple(players)))
    duplicated = replace(
        base,
        board=(base.hole[0], Card(Rank.TWO, Suit.CLUBS), Card(Rank.THREE, Suit.CLUBS)),
    )
    with pytest.raises(ValueError, match="duplicate visible cards"):
        encode_v2(duplicated)


def test_unknown_history_actor_does_not_collide_with_ninth_relative_seat():
    hand = Hand([Player(f"P{index}", 1_000) for index in range(9)], 0, 10, 20, seed=11)
    hand.start()
    base = observation_for(hand)
    ninth_relative_seat = (base.seat + 8) % 9
    event = PublicActionEvent(
        ninth_relative_seat, "preflop", "call", 20, None, 30, 20, False, False
    )
    known = encode_v2(replace(base, history=(event,))).history
    unknown = encode_v2(replace(base, history=(replace(event, seat=-1),))).history

    assert known != unknown
    assert known[0][8] == 1.0
    assert unknown[0][9] == 1.0


def test_encoder_v2_rejects_unknown_history_street():
    base = _observation()
    event = replace(base.history[0], street="typo_street")
    with pytest.raises(ValueError, match="unknown public street"):
        encode_v2(replace(base, history=(event,)))


def test_encoder_v2_fails_closed_instead_of_silently_truncating_history():
    base = _observation()
    event = base.history[0]
    with pytest.raises(ValueError, match="exceeds the Expert v2 trained window"):
        encode_v2(replace(base, history=(event,) * (MAX_HISTORY + 1)))


def test_future_history_does_not_mutate_a_past_observation_snapshot():
    hand = Hand([Player(f"P{index}", 1_000) for index in range(2)], 0, 10, 20, seed=9)
    hand.start()
    past = observation_for(hand)
    encoded_past = encode_v2(past)
    hand.apply(Action(ActionType.CALL))
    assert encode_v2(past) == encoded_past
    assert len(observation_for(hand).history) == len(past.history) + 1
