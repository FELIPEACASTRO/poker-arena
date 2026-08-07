"""Pure OCR amount-normalization tests (no RapidOCR dependency required)."""

import pytest

from poker_arena.vision.ocr import _parse_amount


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Pot: 250", 250),
        ("$1,500", 1500),
        ("1 500", 1500),
        ("1.5K", 1500),
        ("1,5k", 1500),
        ("2M", 2_000_000),
        (250, 250),
    ],
)
def test_parse_amount_normalizes_unambiguous_chip_amounts(raw, expected):
    assert _parse_amount(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "$10.50",
        "1.2.3",
        "stack 10 / bet 20",
        "-50",
        "NaN",
        "",
        None,
        True,
        1_000_000_000.0,
    ],
)
def test_parse_amount_rejects_ambiguous_or_invalid_values(raw):
    assert _parse_amount(raw) is None
