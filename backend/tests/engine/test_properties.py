"""Generative invariants for the poker engine's highest-risk state transitions."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from poker_arena.engine.actions import Action, ActionType
from poker_arena.engine.cards import Deck
from poker_arena.engine.evaluator import card_from_str, compare, evaluate
from poker_arena.engine.game import Hand
from poker_arena.engine.player import Player

RANKS = "23456789TJQKA"
SUITS = "shdc"
CARD_TEXT = [rank + suit for rank in RANKS for suit in SUITS]


@given(seed=st.integers(), chunks=st.lists(st.integers(0, 20), min_size=1, max_size=8))
@settings(max_examples=100, deadline=None)
def test_deck_partition_is_unique_and_conserves_all_cards(seed: int, chunks: list[int]):
    deck = Deck(seed)
    deck.shuffle()
    original = list(deck.cards)
    dealt = []
    for requested in chunks:
        take = min(requested, len(deck.cards))
        dealt.extend(deck.deal(take))

    assert len(dealt) + len(deck.cards) == 52
    assert len(set(dealt + deck.cards)) == 52
    assert set(dealt + deck.cards) == set(original)


@given(seed=st.integers(), invalid=st.one_of(st.integers(max_value=-1), st.integers(min_value=53)))
def test_invalid_deal_is_atomic(seed: int, invalid: int):
    deck = Deck(seed)
    before = list(deck.cards)
    with pytest.raises(ValueError):
        deck.deal(invalid)
    assert deck.cards == before


@given(cards=st.lists(st.sampled_from(CARD_TEXT), min_size=9, max_size=9, unique=True))
@settings(max_examples=100, deadline=None)
def test_evaluator_is_permutation_invariant_and_compare_is_antisymmetric(cards: list[str]):
    parsed = [card_from_str(card) for card in cards]
    hole_a, hole_b, board = parsed[:2], parsed[2:4], parsed[4:9]

    assert evaluate(hole_a, board) == evaluate(list(reversed(hole_a)), list(reversed(board)))
    assert compare(hole_a, hole_b, board) == -compare(hole_b, hole_a, board)
    assert compare(hole_a, hole_a, board) == 0


@given(
    stacks=st.lists(st.integers(min_value=20, max_value=500), min_size=2, max_size=9),
    seed=st.integers(),
)
@settings(max_examples=100, deadline=None)
def test_check_call_showdown_conserves_chips_and_cards(stacks: list[int], seed: int):
    players = [Player(f"P{index}", stack) for index, stack in enumerate(stacks)]
    initial_chips = sum(stacks)
    hand = Hand(players, button=len(players) - 1, small_blind=10, big_blind=20, seed=seed)
    hand.start()

    def passive_strategy(current: Hand) -> Action:
        legal = current.legal_actions()
        if ActionType.CHECK in legal:
            return Action(ActionType.CHECK)
        if ActionType.CALL in legal:
            return Action(ActionType.CALL)
        return Action(ActionType.FOLD)

    winners = hand.play_out(passive_strategy)
    visible_cards = [card for player in players for card in player.hole] + hand.board

    assert winners
    assert sum(player.stack for player in players) == initial_chips
    assert len(visible_cards) == len(set(visible_cards))
    assert len(hand.board) in {0, 5}
