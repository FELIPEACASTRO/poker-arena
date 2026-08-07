from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts.copilot_performance_benchmark import (
    RECEIPT_MAX_AGE_DAYS,
    SCENARIOS,
    benchmark,
    execution_environment,
    implementation_binding,
    installed_distribution_versions,
    nearest_rank_p95,
)


def test_nearest_rank_p95_is_conservative_for_small_receipts():
    assert nearest_rank_p95([5.0, 1.0, 4.0, 2.0, 3.0]) == 5.0
    with pytest.raises(ValueError, match="must not be empty"):
        nearest_rank_p95([])


def test_benchmark_rejects_non_evidential_sample_count():
    with pytest.raises(ValueError, match="at least three"):
        benchmark(2)


def test_scenarios_cover_exact_sampled_heads_up_and_nine_max():
    names = {scenario["name"] for scenario in SCENARIOS}
    assert "river-heads-up-exact" in names
    assert "preflop-heads-up-adaptive" in names
    assert any(scenario["num_opponents"] == 8 for scenario in SCENARIOS)


def test_performance_receipt_is_bound_to_implementation_and_scenarios():
    receipt = benchmark(3)

    assert receipt["schema_version"] == 4
    assert receipt["implementation_binding"] == implementation_binding()
    assert receipt["environment"]["installed_distributions"] == installed_distribution_versions()
    assert receipt["environment"]["processor"] != "not-reported"
    assert len(receipt["scenarios_sha256"]) == 64


def test_versioned_performance_receipt_matches_current_source_and_contract():
    backend_root = Path(__file__).resolve().parents[2]
    receipt = json.loads(
        (backend_root / "scripts" / "copilot_performance_evidence" / "metrics.json").read_text(
            encoding="utf-8"
        )
    )
    scenarios_sha256 = hashlib.sha256(
        json.dumps(SCENARIOS, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    assert receipt["schema_version"] == 4
    assert receipt["implementation_binding"] == implementation_binding()
    assert receipt["scenarios_sha256"] == scenarios_sha256
    assert receipt["environment"] == execution_environment()
    created = datetime.fromisoformat(receipt["created_at_utc"])
    assert created.tzinfo is not None
    assert timedelta(0) <= datetime.now(UTC) - created <= timedelta(days=RECEIPT_MAX_AGE_DAYS)
    assert receipt["scope"] == "local_post_hand_latency_only_not_strategy_quality"
    assert receipt["acceptance"]["all_scenarios_within_budget"] is True
    assert all(row["within_p95_budget"] for row in receipt["scenarios"])
