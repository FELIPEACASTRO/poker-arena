import hashlib
import json
from pathlib import Path

import pytest

from scripts.convert_pluribus import _settlement_from_finishing, convert_hand

ROOT = Path(__file__).resolve().parents[2]


def _raw(actions):
    return {
        "variant": "NT",
        "antes": [0, 0],
        "players": ["Pluribus", "Pro"],
        "starting_stacks": [100, 100],
        "blinds_or_straddles": [1, 2],
        "min_bet": 2,
        "finishing_stacks": [99, 101],
        "actions": actions,
    }


def test_rejects_raise_to_less_than_current_commitment():
    with pytest.raises(ValueError, match="cbr"):
        convert_hand(_raw(["p1 cbr 0"]), 1)


def test_rejects_duplicate_or_malformed_board_cards():
    with pytest.raises(ValueError, match="board|carta"):
        convert_hand(_raw(["d db AsAs2d"]), 1)


def test_uncalled_excess_is_refunded_and_excluded_from_contestable_pot():
    pot, winners, refunds = _settlement_from_finishing(
        starts=[100, 100],
        finishing=[102, 98],
        committed=[50, 2],
        folded=[False, True],
        names=["Winner", "Folded"],
        hand_no=1,
    )

    assert pot == 4
    assert winners == [{"seat": 0, "name": "Winner", "award": 4}]
    assert refunds == [{"seat": 0, "name": "Winner", "amount": 48}]


def test_converter_rejects_finishing_stacks_not_reproduced_by_pokerkit():
    raw = _raw(
        [
            "d dh p1 AsAh",
            "d dh p2 KcKd",
            "p1 cc",
            "p2 cc",
            "d db 2s3s4s",
            "p2 cc",
            "p1 cc",
            "d db 5s",
            "p2 cc",
            "p1 cc",
            "d db 6s",
            "p2 cc",
            "p1 cc",
        ]
    )
    raw["finishing_stacks"] = [90, 110]

    with pytest.raises(ValueError, match="PokerKit"):
        convert_hand(raw, 2)


def test_bundled_pluribus_snapshot_has_pinned_lineage_and_settlement_regression():
    records = [
        json.loads(line)
        for line in (ROOT / "poker_arena" / "data" / "pluribus.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    metadata, hands = records[0], records[1:]

    assert metadata["upstream_git_commit"] == "e47fbd5816372360bade4de5d712346fe1bb70f6"
    assert metadata["upstream_file_count"] == 13 == len(hands)
    assert (
        metadata["converter_sha256"]
        == hashlib.sha256((ROOT / "scripts" / "convert_pluribus.py").read_bytes()).hexdigest()
    )
    assert [hand["pot"] for hand in hands] == [
        250,
        200,
        3000,
        100,
        450,
        250,
        2750,
        1100,
        500,
        4500,
        775,
        600,
        250,
    ]
    assert all(len(hand["source_sha256"]) == 64 for hand in hands)
