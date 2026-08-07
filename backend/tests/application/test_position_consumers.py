from poker_arena.application.copilot import _position_factor
from poker_arena.application.watch_stats import bucket_of


def test_copilot_orders_all_standard_positions_from_early_to_late():
    positions = ["UTG", "UTG+1", "MP", "LJ", "HJ", "CO", "BTN"]
    factors = [_position_factor(position) for position in positions]
    assert factors == sorted(factors)
    assert len(set(factors)) == len(factors)


def test_watch_stats_buckets_all_standard_positions():
    assert bucket_of("SB") == bucket_of("BB") == "blinds"
    assert bucket_of("UTG") == bucket_of("UTG+1") == "early"
    assert bucket_of("MP") == bucket_of("LJ") == "middle"
    assert bucket_of("HJ") == bucket_of("CO") == bucket_of("BTN") == "late"
