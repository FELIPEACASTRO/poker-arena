from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from scripts.copilot_performance_benchmark import (
    RECEIPT_MAX_AGE_DAYS,
    RECEIPT_PATH,
    RECEIPT_SCOPE,
    SCENARIOS,
    benchmark,
    implementation_binding,
    installed_distribution_versions,
    nearest_rank_p95,
    validate_versioned_receipt,
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

    assert receipt["schema_version"] == 5
    assert receipt["scope"] == RECEIPT_SCOPE
    assert receipt["implementation_binding"] == implementation_binding()
    assert receipt["environment"]["installed_distributions"] == installed_distribution_versions()
    assert receipt["environment"]["processor"] != "not-reported"
    assert len(receipt["scenarios_sha256"]) == 64


def test_versioned_performance_receipt_matches_current_source_and_contract():
    receipt = validate_versioned_receipt()

    assert receipt["schema_version"] == 5
    assert receipt["implementation_binding"] == implementation_binding()


def test_versioned_performance_receipt_rejects_expiry(tmp_path):
    receipt = validate_versioned_receipt()
    created = datetime.fromisoformat(receipt["created_at_utc"])

    with pytest.raises(ValueError, match="expirado"):
        validate_versioned_receipt(now=created + timedelta(days=RECEIPT_MAX_AGE_DAYS + 1))


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda row: row["latency_ms"].__setitem__("p95_nearest_rank", 0), "amostras brutas"),
        (lambda row: row.__setitem__("within_p95_budget", False), "flag de latência"),
        (lambda row: row.__setitem__("name", "outro"), "identidade/ordem"),
        (lambda row: row.__setitem__("iterations", 3), "amostragem"),
    ],
)
def test_versioned_performance_receipt_recomputes_claims(tmp_path, mutation, message):
    receipt = deepcopy(validate_versioned_receipt())
    mutation(receipt["scenarios"][0])
    candidate = tmp_path / "tampered.json"
    candidate.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        validate_versioned_receipt(candidate)


def test_versioned_performance_receipt_rejects_duplicate_and_nonfinite_json(tmp_path):
    original = RECEIPT_PATH.read_text(encoding="utf-8")
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        original.replace('"schema_version": 5', '"schema_version": 5,\n  "schema_version": 5', 1),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="ausente ou inválido"):
        validate_versioned_receipt(duplicate)

    nonfinite = tmp_path / "nonfinite.json"
    nonfinite.write_text(
        original.replace('"p95_budget_ms": 2500.0', '"p95_budget_ms": NaN', 1), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="ausente ou inválido"):
        validate_versioned_receipt(nonfinite)
