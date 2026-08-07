from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import equity_precision_benchmark


def test_equity_precision_benchmark_proves_exact_candidate() -> None:
    report = equity_precision_benchmark.run_benchmark(scenarios=3, seed=7)

    assert report["scope"] == "heads-up-river-uniform-range-equity-only"
    assert report["schema_version"] == 2
    assert report["implementation_binding"] == equity_precision_benchmark.implementation_binding()
    assert report["strategy_optimality"] is False
    assert report["candidate"]["enumerated_opponent_hands"] == [990]
    assert report["candidate"]["max_absolute_error_percentage_points"] == 0.0
    assert report["acceptance"]["passed"] is True


def test_equity_precision_benchmark_rejects_empty_sample() -> None:
    with pytest.raises(ValueError, match="positivo"):
        equity_precision_benchmark.run_benchmark(scenarios=0, seed=7)


def test_equity_precision_receipt_refuses_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "receipt.json"
    report = equity_precision_benchmark.run_benchmark(scenarios=1, seed=7)
    equity_precision_benchmark._write_new(path, report)

    assert json.loads(path.read_text(encoding="utf-8"))["acceptance"]["passed"] is True
    with pytest.raises(FileExistsError):
        equity_precision_benchmark._write_new(path, report)


def test_versioned_equity_receipt_matches_current_source_and_contract() -> None:
    backend_root = Path(__file__).resolve().parents[2]
    receipt = json.loads(
        (
            backend_root / "scripts" / "equity_precision_evidence" / "river_hu_seed20260807.json"
        ).read_text(encoding="utf-8")
    )

    assert receipt["schema_version"] == 2
    assert receipt["implementation_binding"] == equity_precision_benchmark.implementation_binding()
    assert receipt["scope"] == "heads-up-river-uniform-range-equity-only"
    assert receipt["strategy_optimality"] is False
    assert receipt["seed"] == 20260807
    assert receipt["scenarios"] == 100
    assert receipt["acceptance"]["passed"] is True
