"""Dependency-light canonical position taxonomy shared by API, vision and ML gates."""

from __future__ import annotations

POSITION_BY_PLAYER_COUNT: dict[int, tuple[str, ...]] = {
    2: ("SB", "BB"),
    3: ("BTN", "SB", "BB"),
    4: ("BTN", "SB", "BB", "UTG"),
    5: ("BTN", "SB", "BB", "UTG", "CO"),
    6: ("BTN", "SB", "BB", "UTG", "HJ", "CO"),
    7: ("BTN", "SB", "BB", "UTG", "LJ", "HJ", "CO"),
    8: ("BTN", "SB", "BB", "UTG", "UTG+1", "LJ", "HJ", "CO"),
    9: ("BTN", "SB", "BB", "UTG", "UTG+1", "MP", "LJ", "HJ", "CO"),
}


def valid_positions(player_count: int) -> frozenset[str]:
    """Canonical labels that can exist at a table of this exact size."""
    return frozenset(POSITION_BY_PLAYER_COUNT.get(player_count, ()))


def position_is_compatible(label: str, player_count: int) -> bool:
    """Reject individually valid labels that are impossible for the table size."""
    return label in valid_positions(player_count)
