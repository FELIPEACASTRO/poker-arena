"""Canonical full-ring position names, indexed clockwise from the button."""

import pytest

from poker_arena.application.positions import position, position_full


@pytest.mark.parametrize(
    ("players", "expected"),
    [
        (2, ["SB", "BB"]),
        (3, ["BTN", "SB", "BB"]),
        (4, ["BTN", "SB", "BB", "UTG"]),
        (5, ["BTN", "SB", "BB", "UTG", "CO"]),
        (6, ["BTN", "SB", "BB", "UTG", "HJ", "CO"]),
        (7, ["BTN", "SB", "BB", "UTG", "LJ", "HJ", "CO"]),
        (8, ["BTN", "SB", "BB", "UTG", "UTG+1", "LJ", "HJ", "CO"]),
        (9, ["BTN", "SB", "BB", "UTG", "UTG+1", "MP", "LJ", "HJ", "CO"]),
    ],
)
def test_position_labels_follow_standard_table(players: int, expected: list[str]):
    assert [position(seat, button=0, n=players) for seat in range(players)] == expected


@pytest.mark.parametrize("label", ["BTN", "SB", "BB", "UTG", "UTG+1", "MP", "LJ", "HJ", "CO"])
def test_every_public_label_has_a_full_name(label: str):
    assert position_full(label) != label
