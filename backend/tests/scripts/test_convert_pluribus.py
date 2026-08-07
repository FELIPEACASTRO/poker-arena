import pytest

from scripts.convert_pluribus import convert_hand


def _raw(actions):
    return {
        "players": ["Pluribus", "Pro"],
        "starting_stacks": [100, 100],
        "blinds_or_straddles": [1, 2],
        "finishing_stacks": [99, 101],
        "actions": actions,
    }


def test_rejects_raise_to_less_than_current_commitment():
    with pytest.raises(ValueError, match="cbr"):
        convert_hand(_raw(["p1 cbr 0"]), 1)


def test_rejects_duplicate_or_malformed_board_cards():
    with pytest.raises(ValueError, match="board|carta"):
        convert_hand(_raw(["d db AsAs2d"]), 1)
