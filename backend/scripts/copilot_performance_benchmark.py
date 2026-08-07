"""Reproducible local latency receipt for the complete post-hand copilot review.

The benchmark covers exact and sampled equity, heads-up through nine players. It is
not a strategy-quality benchmark and its latency applies only to the recorded host.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import statistics
import time
from datetime import UTC, datetime, timedelta
from importlib.metadata import distributions
from pathlib import Path
from typing import Any, Final

from poker_arena.application.copilot import review_spot

P95_BUDGET_MS: Final = 2_500.0
RECEIPT_MAX_AGE_DAYS: Final = 30
CANONICAL_RECEIPT_ITERATIONS: Final = 7
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
RECEIPT_PATH: Final = Path(__file__).with_name("copilot_performance_evidence") / "metrics.json"


def _reject_duplicate_receipt_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("receipt de desempenho contém chave JSON duplicada")
        result[key] = value
    return result


def _reject_nonfinite_receipt_constant(value: str) -> None:
    raise ValueError(f"receipt de desempenho contém número não finito: {value}")


def _parse_finite_receipt_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("receipt de desempenho contém número não finito")
    return parsed


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


def _scenarios_sha256() -> str:
    return hashlib.sha256(
        json.dumps(SCENARIOS, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def validate_versioned_receipt(
    path: Path = RECEIPT_PATH, *, now: datetime | None = None
) -> dict[str, Any]:
    """Validate the release receipt without relying on optimized-away assertions."""

    try:
        receipt = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_receipt_keys,
            parse_constant=_reject_nonfinite_receipt_constant,
            parse_float=_parse_finite_receipt_float,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, OverflowError) as exc:
        raise ValueError("receipt de desempenho ausente ou inválido") from exc
    if not isinstance(receipt, dict) or receipt.get("schema_version") != 5:
        raise ValueError("schema do receipt de desempenho é inválido")
    if receipt.get("implementation_binding") != implementation_binding():
        raise ValueError("receipt de desempenho não corresponde ao código atual")
    if receipt.get("scenarios_sha256") != _scenarios_sha256():
        raise ValueError("receipt de desempenho não corresponde aos cenários atuais")
    if receipt.get("environment") != execution_environment():
        raise ValueError("receipt de desempenho não corresponde ao ambiente instalado")
    try:
        created = datetime.fromisoformat(receipt["created_at_utc"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("timestamp do receipt de desempenho é inválido") from exc
    reference = now or datetime.now(UTC)
    if created.tzinfo is None or not timedelta(0) <= reference - created <= timedelta(
        days=RECEIPT_MAX_AGE_DAYS
    ):
        raise ValueError("receipt de desempenho está no futuro ou expirado")
    if receipt.get("scope") != "local_post_hand_latency_only_not_strategy_quality":
        raise ValueError("escopo do receipt de desempenho é inválido")
    if receipt.get("p95_budget_ms") != P95_BUDGET_MS:
        raise ValueError("budget do receipt de desempenho é inválido")
    if receipt.get("warmup_runs_per_scenario") != 1:
        raise ValueError("política de warm-up do receipt de desempenho é inválida")
    scenarios = receipt.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) != len(SCENARIOS):
        raise ValueError("cenários do receipt de desempenho estão incompletos")
    if [row.get("name") for row in scenarios if isinstance(row, dict)] != [
        scenario["name"] for scenario in SCENARIOS
    ]:
        raise ValueError("identidade/ordem dos cenários de desempenho divergiu")
    derived_acceptance: list[bool] = []
    for row in scenarios:
        if not isinstance(row, dict) or row.get("iterations") != CANONICAL_RECEIPT_ITERATIONS:
            raise ValueError("amostragem do receipt de desempenho é inválida")
        samples = row.get("samples_ms")
        if (
            not isinstance(samples, list)
            or len(samples) != CANONICAL_RECEIPT_ITERATIONS
            or any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                or value < 0
                for value in samples
            )
        ):
            raise ValueError("amostras brutas do receipt de desempenho são inválidas")
        latency = row.get("latency_ms")
        expected_latency = {
            "min": min(samples),
            "median": round(statistics.median(samples), 3),
            "p95_nearest_rank": round(nearest_rank_p95(samples), 3),
            "max": max(samples),
        }
        if latency != expected_latency:
            raise ValueError("resumo de latência não corresponde às amostras brutas")
        within_budget = expected_latency["p95_nearest_rank"] <= P95_BUDGET_MS
        if row.get("within_p95_budget") is not within_budget:
            raise ValueError("flag de latência não corresponde às amostras brutas")
        if not within_budget:
            raise ValueError("cenário excede o contrato de latência")
        derived_acceptance.append(within_budget)
    acceptance = receipt.get("acceptance")
    if (
        not isinstance(acceptance, dict)
        or acceptance.get("all_scenarios_within_budget") is not all(derived_acceptance)
        or not all(derived_acceptance)
    ):
        raise ValueError("receipt de desempenho não foi aprovado")
    return receipt


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
    samples = [round(value, 3) for value in latencies]
    p95 = nearest_rank_p95(samples)
    return {
        "name": scenario["name"],
        "iterations": iterations,
        "samples_ms": samples,
        "latency_ms": {
            "min": min(samples),
            "median": round(statistics.median(samples), 3),
            "p95_nearest_rank": round(p95, 3),
            "max": max(samples),
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
        "schema_version": 5,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "scope": "local_post_hand_latency_only_not_strategy_quality",
        "environment": environment,
        "implementation_binding": implementation_binding(),
        "scenarios_sha256": _scenarios_sha256(),
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
        default=RECEIPT_PATH,
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
