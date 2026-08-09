from __future__ import annotations

import math

import pytest

import poker_arena.ml.expert_benchmark as benchmark


@pytest.fixture(autouse=True)
def _bounded_draws(monkeypatch):
    monkeypatch.setattr(benchmark, "BOOTSTRAP_DRAWS", 1_000)
    monkeypatch.setattr(benchmark, "SIGN_FLIP_DRAWS", 3_000)


def _panel(value: float = 10.0):
    return {
        cell: tuple(value + (index % 3 - 1) for index in range(benchmark.MIN_BLOCKS_PER_CELL))
        for cell in benchmark.preregistered_cells()
    }


def test_preregistration_covers_three_levels_tables_stacks_and_opponents():
    cells = benchmark.preregistered_cells()
    assert len(cells) == 3 * 3 * 3 * 4
    assert {cell.level for cell in cells} == set(benchmark.LEVELS)
    assert {cell.table_size for cell in cells} == set(benchmark.TABLE_SIZES)
    assert {cell.stack_depth_bb for cell in cells} == set(benchmark.STACK_DEPTHS_BB)


def test_hand_volume_is_rounded_to_complete_seat_button_cycles():
    assert benchmark.balanced_hands_per_block(200, 2) == 200
    assert benchmark.balanced_hands_per_block(200, 6) == 216
    assert benchmark.balanced_hands_per_block(200, 9) == 243


def test_complete_positive_panel_derives_reproducible_simultaneous_evidence():
    raw = _panel()
    first = benchmark.analyze_cells(raw)
    second = benchmark.analyze_cells(raw)
    assert first == second
    assert all(item.estimate_bb100 > 0.0 for item in first)
    assert all(item.simultaneous_ci95[0] > 0.0 for item in first)
    assert all(item.holm_adjusted_p_value <= 0.05 for item in first)


def test_incomplete_panel_cannot_cherry_pick_easy_opponents():
    raw = _panel()
    raw.pop(next(iter(raw)))
    with pytest.raises(ValueError, match="exactly"):
        benchmark.analyze_cells(raw)


@pytest.mark.parametrize("bad", [(), (1.0,) * 29, (math.nan,) * 30, (math.inf,) * 30])
def test_invalid_or_underpowered_blocks_fail_closed(bad):
    raw = _panel()
    raw[next(iter(raw))] = bad
    with pytest.raises(ValueError):
        benchmark.analyze_cells(raw)


def test_holm_adjustment_is_monotone_and_never_smaller_than_raw_p():
    raw = [0.001, 0.02, 0.03, 0.5]
    adjusted = benchmark._holm_adjust(raw)
    assert all(adjusted[index] >= raw[index] for index in range(len(raw)))
    ordered = [adjusted[index] for index in sorted(range(len(raw)), key=raw.__getitem__)]
    assert ordered == sorted(ordered)
