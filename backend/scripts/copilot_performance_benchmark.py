"""Reproducible local latency receipt for the complete post-hand copilot review.

The benchmark covers exact and sampled equity, heads-up through nine players. It is
not a strategy-quality benchmark and its latency applies only to the recorded host.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import time
from datetime import UTC, datetime
from importlib.metadata import distributions
from pathlib import Path
from typing import Any, Final

from poker_arena.application.copilot import review_spot

P95_BUDGET_MS: Final = 2_500.0
RECEIPT_MAX_AGE_DAYS: Final = 30
SCENARIOS: Final = (
    {
        "name": "river-heads-up-exact",
        "hole": ["As", "Kd"],
        "board": ["2h", "6c", "Tc", "3s", "9d"],
        "pot": 100,
        "to_call": 20,
        "my_stack": 1_000,
        "num_opponents": 1,
        "position": "SB",
    },
    {
        "name": "preflop-heads-up-adaptive",
        "hole": ["As", "Kh"],
        "board": [],
        "pot": 30,
        "to_call": 10,
        "my_stack": 1_000,
        "num_opponents": 1,
        "position": "SB",
    },
    {
        "name": "preflop-six-max",
        "hole": ["Qd", "Jc"],
        "board": [],
        "pot": 40,
        "to_call": 20,
        "my_stack": 1_000,
        "num_opponents": 5,
        "position": "UTG",
    },
    {
        "name": "preflop-nine-max",
        "hole": ["8d", "7d"],
        "board": [],
        "pot": 60,
        "to_call": 20,
        "my_stack": 1_000,
        "num_opponents": 8,
        "position": "MP",
    },
    {
        "name": "flop-six-max",
        "hole": ["Ah", "Kh"],
        "board": ["Qh", "Jh", "2c"],
        "pot": 120,
        "to_call": 40,
        "my_stack": 1_000,
        "num_opponents": 5,
        "position": "CO",
    },
)
BACKEND_ROOT: Final = Path(__file__).resolve().parents[1]


def _bound_paths() -> tuple[Path, ...]:
    """Bind the complete local implementation transitively used by review_spot.

    A narrow hand-maintained import list silently becomes stale when an indirect
    policy/view/helper changes. Hashing every package source is conservative and
    makes the versioned latency receipt fail closed under any backend code drift.
    """

    package_sources = sorted((BACKEND_ROOT / "poker_arena").rglob("*.py"))
    return (Path(__file__).resolve(), *package_sources, BACKEND_ROOT / "uv.lock")


def implementation_binding() -> dict[str, Any]:
    files = {
        path.relative_to(BACKEND_ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in _bound_paths()
    }
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return {"sha256": hashlib.sha256(canonical).hexdigest(), "files": files}


def installed_distribution_versions() -> list[dict[str, str]]:
    """Return the complete installed Python distribution/version fingerprint.

    The lockfile is an input declaration, not proof of what this interpreter loaded.
    Recording every installed distribution makes a versioned latency receipt fail
    closed when the local virtual environment drifts without a source/lock change.
    """

    rows = {
        (
            (distribution.metadata.get("Name") or "unknown").strip().casefold().replace("_", "-"),
            distribution.version,
        )
        for distribution in distributions()
    }
    return [{"name": name, "version": version} for name, version in sorted(rows)]


def execution_environment() -> dict[str, Any]:
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine() or "not-reported",
        "processor": platform.processor()
        or os.environ.get("PROCESSOR_IDENTIFIER")
        or "not-reported",
        "logical_cpu_count": os.cpu_count() or 1,
        "installed_distributions": installed_distribution_versions(),
    }


def nearest_rank_p95(values: list[float]) -> float:
    """Return the deterministic nearest-rank P95 used by the receipt."""
    if not values:
        raise ValueError("latency sample must not be empty")
    ordered = sorted(values)
    rank = max(1, (95 * len(ordered) + 99) // 100)
    return ordered[rank - 1]


def _run_scenario(scenario: dict[str, Any], iterations: int) -> dict[str, Any]:
    kwargs = {key: value for key, value in scenario.items() if key not in {"name", "hole", "board"}}
    kwargs["hole_cards"] = scenario["hole"]
    kwargs["board_cards"] = scenario["board"]
    kwargs.update({"in_position": True, "available_levels": []})
    review_spot(**kwargs)  # warm-up excluded
    latencies: list[float] = []
    view = None
    for _ in range(iterations):
        started = time.perf_counter()
        view = review_spot(**kwargs)
        latencies.append((time.perf_counter() - started) * 1_000)
    if view is None:  # defensive: benchmark() already rejects a zero iteration count
        raise RuntimeError("no measured copilot result")
    p95 = nearest_rank_p95(latencies)
    return {
        "name": scenario["name"],
        "iterations": iterations,
        "latency_ms": {
            "min": round(min(latencies), 3),
            "median": round(statistics.median(latencies), 3),
            "p95_nearest_rank": round(p95, 3),
            "max": round(max(latencies), 3),
        },
        "equity_method": view.equity_method,
        "equity_trials": view.equity_trials,
        "recommendation_stable": view.recommendation_stable,
        "within_p95_budget": p95 <= P95_BUDGET_MS,
    }


def benchmark(iterations: int) -> dict[str, Any]:
    if iterations < 3:
        raise ValueError("use at least three measured iterations")
    environment = execution_environment()
    if "not-reported" in {environment["machine"], environment["processor"]}:
        raise RuntimeError("machine and processor identity must be reported for latency evidence")
    rows = [_run_scenario(dict(scenario), iterations) for scenario in SCENARIOS]
    return {
        "schema_version": 4,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "scope": "local_post_hand_latency_only_not_strategy_quality",
        "environment": environment,
        "implementation_binding": implementation_binding(),
        "scenarios_sha256": hashlib.sha256(
            json.dumps(SCENARIOS, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "warmup_runs_per_scenario": 1,
        "p95_budget_ms": P95_BUDGET_MS,
        "scenarios": rows,
        "acceptance": {
            "all_scenarios_within_budget": all(row["within_p95_budget"] for row in rows)
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=7)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("copilot_performance_evidence") / "metrics.json",
    )
    args = parser.parse_args()
    receipt = benchmark(args.iterations)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if receipt["acceptance"]["all_scenarios_within_budget"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
