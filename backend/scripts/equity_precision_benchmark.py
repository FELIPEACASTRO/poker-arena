"""Paired benchmark of sampled versus exact heads-up river equity.

This benchmark measures numerical equity precision only. It is not evidence of
strategy optimality because both methods assume a uniformly random opponent range.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import random
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from poker_arena.bots.monte_carlo_bot import estimate_equity_with_uncertainty
from poker_arena.engine.evaluator import card_from_str

CARD_NAMES = [rank + suit for rank in "23456789TJQKA" for suit in "shdc"]
BASELINE_SAMPLES = 400
EXACT_P95_BUDGET_MS = 250.0
DECISION_THRESHOLDS = (0.20, 0.33, 0.50, 0.67)
BACKEND_ROOT = Path(__file__).resolve().parents[1]
BOUND_PATHS = (
    Path(__file__).resolve(),
    BACKEND_ROOT / "poker_arena" / "bots" / "monte_carlo_bot.py",
    BACKEND_ROOT / "poker_arena" / "engine" / "evaluator.py",
    BACKEND_ROOT / "uv.lock",
)


def implementation_binding() -> dict[str, Any]:
    files = {
        path.relative_to(BACKEND_ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in BOUND_PATHS
    }
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return {"sha256": hashlib.sha256(canonical).hexdigest(), "files": files}


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def run_benchmark(*, scenarios: int, seed: int) -> dict[str, Any]:
    if scenarios < 1:
        raise ValueError("scenarios precisa ser positivo")
    generator = random.Random(seed)  # noqa: S311 - reproducible scientific benchmark
    baseline_errors: list[float] = []
    baseline_latencies: list[float] = []
    exact_latencies: list[float] = []
    baseline_decision_errors = 0
    decision_comparisons = 0
    exact_trials: set[int] = set()

    for scenario_index in range(scenarios):
        names = generator.sample(CARD_NAMES, 7)
        hole = [card_from_str(name) for name in names[:2]]
        board = [card_from_str(name) for name in names[2:]]

        started = time.perf_counter()
        exact = estimate_equity_with_uncertainty(
            hole,
            board,
            1,
            1,
            random.Random(0),  # noqa: S311 - ignored by exact enumeration
        )
        exact_latencies.append((time.perf_counter() - started) * 1_000)
        exact_trials.add(exact.trials)

        started = time.perf_counter()
        baseline = estimate_equity_with_uncertainty(
            hole,
            board,
            1,
            BASELINE_SAMPLES,
            random.Random(seed + scenario_index + 1),  # noqa: S311
            exact_when_possible=False,
        )
        baseline_latencies.append((time.perf_counter() - started) * 1_000)
        baseline_errors.append(abs(baseline.equity - exact.equity))
        for threshold in DECISION_THRESHOLDS:
            baseline_decision_errors += (baseline.equity >= threshold) != (
                exact.equity >= threshold
            )
            decision_comparisons += 1

    exact_p95 = _percentile(exact_latencies, 0.95)
    passed = exact_trials == {990} and exact_p95 <= EXACT_P95_BUDGET_MS
    return {
        "schema_version": 2,
        "scope": "heads-up-river-uniform-range-equity-only",
        "strategy_optimality": False,
        "implementation_binding": implementation_binding(),
        "seed": seed,
        "scenarios": scenarios,
        "environment": {
            "python": platform.python_version(),
            "os": platform.platform(),
            "processor": platform.processor() or "unknown",
        },
        "baseline": {
            "method": "monte-carlo-uniform-range",
            "samples": BASELINE_SAMPLES,
            "mae_percentage_points": round(statistics.fmean(baseline_errors) * 100, 6),
            "p95_absolute_error_percentage_points": round(
                _percentile(baseline_errors, 0.95) * 100, 6
            ),
            "max_absolute_error_percentage_points": round(max(baseline_errors) * 100, 6),
            "decision_mismatch_rate": round(baseline_decision_errors / decision_comparisons, 6),
            "latency_median_ms": round(statistics.median(baseline_latencies), 3),
            "latency_p95_ms": round(_percentile(baseline_latencies, 0.95), 3),
        },
        "candidate": {
            "method": "exact-river-heads-up",
            "enumerated_opponent_hands": sorted(exact_trials),
            "mae_percentage_points": 0.0,
            "p95_absolute_error_percentage_points": 0.0,
            "max_absolute_error_percentage_points": 0.0,
            "decision_mismatch_rate": 0.0,
            "latency_median_ms": round(statistics.median(exact_latencies), 3),
            "latency_p95_ms": round(exact_p95, 3),
        },
        "acceptance": {
            "exact_enumeration": exact_trials == {990},
            "candidate_p95_budget_ms": EXACT_P95_BUDGET_MS,
            "candidate_within_latency_budget": exact_p95 <= EXACT_P95_BUDGET_MS,
            "passed": passed,
        },
    }


def _write_new(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, ensure_ascii=True, indent=2, sort_keys=True)
        stream.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", type=int, default=50)
    parser.add_argument("--seed", type=int, default=20260807)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = run_benchmark(scenarios=args.scenarios, seed=args.seed)
        if args.output is not None:
            _write_new(args.output, report)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "ERROR", "reason": str(exc)}, ensure_ascii=True))
        return 2
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0 if report["acceptance"]["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
