from __future__ import annotations

import pytest

from poker_arena.bots.observation import Observation, PublicPlayer
from poker_arena.engine.actions import ActionType
from poker_arena.engine.cards import Card, Rank, Suit
from poker_arena.ml.action_space_v2 import (
    ACTIONS_V2,
    N_ACTIONS_V2,
    legal_mask_v2,
    to_action_v2,
)


def _obs(*, scale: int = 1, stack: int = 1_000, min_raise_to: int = 60) -> Observation:
    players = (
        PublicPlayer(0, "hero", stack * scale, 20 * scale, 20 * scale, "active", False),
        PublicPlayer(1, "villain", 1_000 * scale, 40 * scale, 40 * scale, "active", True),
    )
    return Observation(
        seat=0,
        hole=(Card(Rank.ACE, Suit.SPADES), Card(Rank.KING, Suit.HEARTS)),
        board=(),
        pot=100 * scale,
        to_call=20 * scale,
        current_bet=40 * scale,
        min_raise_to=min_raise_to * scale,
        legal_actions=frozenset(
            {ActionType.FOLD, ActionType.CALL, ActionType.RAISE, ActionType.ALL_IN}
        ),
        players=players,
        num_active=2,
    )


def test_v2_contract_has_ten_named_actions():
    assert N_ACTIONS_V2 == len(ACTIONS_V2) == 10
    assert len(set(ACTIONS_V2)) == 10


def test_every_unmasked_index_maps_to_one_legal_action_without_aliases():
    obs = _obs()
    actions = [
        to_action_v2(obs, index) for index, enabled in enumerate(legal_mask_v2(obs)) if enabled
    ]
    signatures = [(action.type, action.amount) for action in actions]
    assert len(signatures) == len(set(signatures))
    assert all(action.type in obs.legal_actions for action in actions)


def test_raise_targets_are_scale_equivariant():
    base = _obs(scale=1)
    scaled = _obs(scale=100)
    for index in range(N_ACTIONS_V2):
        if legal_mask_v2(base)[index] and legal_mask_v2(scaled)[index]:
            action = to_action_v2(base, index)
            scaled_action = to_action_v2(scaled, index)
            assert action.type is scaled_action.type
            assert scaled_action.amount == action.amount * 100


def test_fractional_raise_that_collapses_to_minimum_is_masked_as_alias():
    obs = _obs(min_raise_to=200)
    mask = legal_mask_v2(obs)
    assert mask[2] is True
    assert sum(mask[3:9]) < 6


def test_raise_abstractions_do_not_silently_become_all_in():
    obs = _obs(stack=50, min_raise_to=60)
    mask = legal_mask_v2(obs)
    assert mask[9] is True
    assert all(
        to_action_v2(obs, index).amount < 70
        for index, enabled in enumerate(mask[2:9], start=2)
        if enabled
    )


@pytest.mark.parametrize("index", [-1, 10, True, 1.5, "1"])
def test_invalid_or_masked_indices_fail_closed(index):
    obs = _obs()
    expected = TypeError if type(index) is not int else ValueError
    with pytest.raises(expected):
        to_action_v2(obs, index)
