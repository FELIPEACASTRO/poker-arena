"""Pre-registered, paired-block evaluation primitives for Expert v2.

Poker outcomes are too noisy for a raw win-rate or a short winning streak to be
promotion evidence.  This module freezes the evaluation cells and computes
deterministic paired bootstrap intervals plus Holm-adjusted sign-flip tests.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from statistics import fmean
from typing import Final

import numpy as np

LEVELS: Final = ("beginner", "intermediate", "advanced")
TABLE_SIZES: Final = (2, 6, 9)
STACK_DEPTHS_BB: Final = (20, 50, 100, 200)
MIN_BLOCKS_PER_CELL: Final = 30
MIN_HANDS_PER_BLOCK: Final = 200
BOOTSTRAP_DRAWS: Final = 20_000
SIGN_FLIP_DRAWS: Final = 50_000
RAW_RESULTS_PROFILE_REVISION: Final = "poker-arena-expert-raw-results-v2-2026-08-08"
ACTION_COUNT_KEYS: Final = ("fold", "check", "call", "raise", "all_in")
_EXECUTION_FIELDS: Final = frozenset(
    {
        "candidate_artifact_sha256",
        "candidate_manifest_sha256",
        "candidate_contract_sha256",
        "baseline_policy_sha256",
        "decision_rule",
        "engine_sha256",
        "runner_sha256",
        "opponent_panel_sha256",
        "binding_sha256",
    }
)

OPPONENT_PANEL: Final = {
    "beginner": ("random", "calling_station", "nit"),
    "intermediate": ("heuristic", "montecarlo_300", "maniac"),
    "advanced": ("heuristic_tight", "montecarlo_1000", "montecarlo_3000"),
}


@dataclass(frozen=True, slots=True)
class BenchmarkCell:
    level: str
    opponent: str
    table_size: int
    stack_depth_bb: int

    @property
    def identifier(self) -> str:
        return f"{self.level}:{self.opponent}:{self.table_size}:{self.stack_depth_bb}"


@dataclass(frozen=True, slots=True)
class CellEvidence:
    cell: BenchmarkCell
    block_deltas_bb100: tuple[float, ...]
    estimate_bb100: float
    simultaneous_ci95: tuple[float, float]
    one_sided_p_value: float
    holm_adjusted_p_value: float


@dataclass(frozen=True, slots=True)
class RawBenchmarkSummary:
    hands: int
    decisions: int
    blocks: int
    illegal_actions: int
    non_finite_outputs: int
    fallbacks: int
    aggregate: tuple[float, float, float]
    worst_cell: tuple[float, float, float]
    max_ci_half_width: float
    max_holm_adjusted_p_value: float
    execution_binding_sha256: str


def preregistered_cells() -> tuple[BenchmarkCell, ...]:
    return tuple(
        BenchmarkCell(level, opponent, table_size, stack_depth)
        for level in LEVELS
        for opponent in OPPONENT_PANEL[level]
        for table_size in TABLE_SIZES
        for stack_depth in STACK_DEPTHS_BB
    )


def balanced_hands_per_block(minimum: int, table_size: int) -> int:
    """Round up to a complete hero-seat × button counterbalancing cycle."""

    if type(minimum) is not int or minimum < MIN_HANDS_PER_BLOCK:
        raise ValueError("hands per block is below the preregistered minimum")
    if table_size not in TABLE_SIZES:
        raise ValueError("table size is outside the preregistered panel")
    cycle = table_size * table_size
    return ((minimum + cycle - 1) // cycle) * cycle


def _hash_files(paths: tuple[Path, ...], root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix().encode()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def current_execution_binding() -> dict[str, str]:
    """Hash the exact engine, statistics runner and opponent implementations."""

    backend_root = Path(__file__).resolve().parents[2]
    engine_files = tuple((backend_root / "poker_arena" / "engine").glob("*.py"))
    runner_files = (
        Path(__file__).resolve(),
        backend_root / "poker_arena" / "ml" / "expert_benchmark_runner.py",
    )
    opponent_files = (
        backend_root / "poker_arena" / "ml" / "benchmark_opponents.py",
        backend_root / "poker_arena" / "bots" / "heuristic_bot.py",
        backend_root / "poker_arena" / "bots" / "monte_carlo_bot.py",
        backend_root / "poker_arena" / "bots" / "random_bot.py",
    )
    panel_payload = json.dumps(
        OPPONENT_PANEL, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    opponent_digest = hashlib.sha256()
    opponent_digest.update(bytes.fromhex(_hash_files(opponent_files, backend_root)))
    opponent_digest.update(panel_payload)
    return {
        "engine_sha256": _hash_files(engine_files, backend_root),
        "runner_sha256": _hash_files(runner_files, backend_root),
        "opponent_panel_sha256": opponent_digest.hexdigest(),
    }


def execution_binding_sha256(execution: dict[str, object]) -> str:
    bound = {key: value for key, value in execution.items() if key != "binding_sha256"}
    payload = json.dumps(
        bound, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _seed(identifier: str, purpose: str) -> int:
    digest = hashlib.sha256(f"{purpose}:{identifier}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _validate_deltas(deltas: tuple[float, ...]) -> None:
    if len(deltas) < MIN_BLOCKS_PER_CELL:
        raise ValueError("each benchmark cell requires at least 30 independent blocks")
    if any(isinstance(value, bool) or not math.isfinite(float(value)) for value in deltas):
        raise ValueError("block deltas must be finite numbers")


def _quantile(sorted_values: list[float], probability: float) -> float:
    if not 0.0 <= probability <= 1.0:
        raise ValueError("probability must be within [0, 1]")
    position = probability * (len(sorted_values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def _paired_bootstrap_ci(
    cell: BenchmarkCell, deltas: tuple[float, ...], *, family_size: int
) -> tuple[float, float]:
    rng = np.random.default_rng(_seed(cell.identifier, "bootstrap"))
    values = np.asarray(deltas, dtype=np.float64)
    indices = rng.integers(0, len(values), size=(BOOTSTRAP_DRAWS, len(values)))
    estimates = np.sort(values[indices].mean(axis=1)).tolist()
    tail = 0.05 / (2.0 * family_size)
    return _quantile(estimates, tail), _quantile(estimates, 1.0 - tail)


def _sign_flip_p_value(cell: BenchmarkCell, deltas: tuple[float, ...]) -> float:
    """One-sided randomization test of mean(delta) <= 0, deterministic by cell."""

    observed = fmean(deltas)
    if observed <= 0.0:
        return 1.0
    rng = np.random.default_rng(_seed(cell.identifier, "sign-flip"))
    values = np.asarray(deltas, dtype=np.float64)
    signs = rng.integers(0, 2, size=(SIGN_FLIP_DRAWS, len(values)), dtype=np.int8)
    signs = signs * 2 - 1
    permuted = (signs * values).mean(axis=1)
    exceedances = int(np.count_nonzero(permuted >= observed))
    return (exceedances + 1) / (SIGN_FLIP_DRAWS + 1)


def _holm_adjust(p_values: list[float]) -> list[float]:
    order = sorted(range(len(p_values)), key=p_values.__getitem__)
    adjusted = [1.0] * len(p_values)
    running = 0.0
    family_size = len(p_values)
    for rank, index in enumerate(order):
        candidate = min(1.0, (family_size - rank) * p_values[index])
        running = max(running, candidate)
        adjusted[index] = running
    return adjusted


def analyze_cells(
    raw: dict[BenchmarkCell, tuple[float, ...]],
) -> tuple[CellEvidence, ...]:
    """Reject incomplete panels and derive all claims from paired raw blocks."""

    expected = set(preregistered_cells())
    if set(raw) != expected:
        raise ValueError("benchmark panel must match the preregistered cells exactly")
    ordered = preregistered_cells()
    for cell in ordered:
        _validate_deltas(raw[cell])
    p_values = [_sign_flip_p_value(cell, raw[cell]) for cell in ordered]
    adjusted = _holm_adjust(p_values)
    return tuple(
        CellEvidence(
            cell=cell,
            block_deltas_bb100=raw[cell],
            estimate_bb100=fmean(raw[cell]),
            simultaneous_ci95=_paired_bootstrap_ci(cell, raw[cell], family_size=len(ordered)),
            one_sided_p_value=p_values[index],
            holm_adjusted_p_value=adjusted[index],
        )
        for index, cell in enumerate(ordered)
    )


@lru_cache(maxsize=16)
def _analyze_frozen_cells(
    values: tuple[tuple[float, ...], ...],
) -> tuple[CellEvidence, ...]:
    cells = preregistered_cells()
    return analyze_cells(dict(zip(cells, values, strict=True)))


def _block_identity(cell: BenchmarkCell, block: dict[str, object]) -> str:
    bound = {
        "cell": cell.identifier,
        **{key: value for key, value in block.items() if key != "id"},
    }
    payload = json.dumps(
        bound, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def summarize_raw_results(raw: object) -> RawBenchmarkSummary:
    """Validate every raw block and derive receipt metrics without trusting claims."""

    if not isinstance(raw, dict) or set(raw) != {
        "schema_version",
        "profile_revision",
        "execution",
        "cells",
    }:
        raise ValueError("raw results root is invalid")
    if raw["schema_version"] != 1 or raw["profile_revision"] != RAW_RESULTS_PROFILE_REVISION:
        raise ValueError("raw results profile is unsupported")
    execution = raw["execution"]
    if not isinstance(execution, dict) or set(execution) != _EXECUTION_FIELDS:
        raise ValueError("raw execution binding is invalid")
    for field in _EXECUTION_FIELDS - {"decision_rule"}:
        value = execution[field]
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise ValueError("raw execution digest is invalid")
    if execution["decision_rule"] not in {"modal", "sampled"}:
        raise ValueError("raw execution decision rule is invalid")
    if execution["binding_sha256"] != execution_binding_sha256(execution):
        raise ValueError("raw execution binding digest is invalid")
    if execution["candidate_artifact_sha256"] == execution["baseline_policy_sha256"]:
        raise ValueError("candidate and baseline identities must differ")
    cells = raw["cells"]
    if not isinstance(cells, list):
        raise ValueError("raw results cells must be an array")
    expected = set(preregistered_cells())
    observed: dict[BenchmarkCell, tuple[float, ...]] = {}
    block_ids: set[str] = set()
    hands = decisions = illegal = non_finite = fallbacks = blocks = 0
    for raw_cell in cells:
        if not isinstance(raw_cell, dict) or set(raw_cell) != {
            "level",
            "opponent",
            "table_size",
            "stack_depth_bb",
            "blocks",
        }:
            raise ValueError("raw benchmark cell is invalid")
        cell = BenchmarkCell(
            raw_cell["level"],
            raw_cell["opponent"],
            raw_cell["table_size"],
            raw_cell["stack_depth_bb"],
        )
        if cell not in expected or cell in observed:
            raise ValueError("raw benchmark panel differs from preregistration")
        raw_blocks = raw_cell["blocks"]
        if not isinstance(raw_blocks, list) or len(raw_blocks) < MIN_BLOCKS_PER_CELL:
            raise ValueError("raw benchmark cell is underpowered")
        deltas: list[float] = []
        for block in raw_blocks:
            if not isinstance(block, dict) or set(block) != {
                "id",
                "deal_seed",
                "candidate_policy_seed",
                "baseline_policy_seed",
                "hands",
                "candidate_chips_delta",
                "baseline_chips_delta",
                "big_blind",
                "decisions",
                "candidate_decisions",
                "baseline_decisions",
                "candidate_action_counts",
                "baseline_action_counts",
                "illegal_actions",
                "non_finite_outputs",
                "fallbacks",
                "execution_binding_sha256",
                "candidate_transcript_sha256",
                "baseline_transcript_sha256",
            }:
                raise ValueError("raw benchmark block is invalid")
            block_id = block["id"]
            if (
                not isinstance(block_id, str)
                or len(block_id) != 64
                or any(character not in "0123456789abcdef" for character in block_id)
                or block_id in block_ids
            ):
                raise ValueError("raw benchmark block identity is invalid")
            for seed_field in ("deal_seed", "candidate_policy_seed", "baseline_policy_seed"):
                if type(block[seed_field]) is not int or block[seed_field] < 0:
                    raise ValueError("raw benchmark seed is invalid")
            for count_field in (
                "hands",
                "decisions",
                "candidate_decisions",
                "baseline_decisions",
                "illegal_actions",
                "non_finite_outputs",
                "fallbacks",
            ):
                if type(block[count_field]) is not int or block[count_field] < 0:
                    raise ValueError("raw benchmark count is invalid")
            if block["decisions"] != (block["candidate_decisions"] + block["baseline_decisions"]):
                raise ValueError("raw benchmark decision totals are inconsistent")
            for prefix in ("candidate", "baseline"):
                action_counts = block[f"{prefix}_action_counts"]
                if (
                    not isinstance(action_counts, dict)
                    or set(action_counts) != set(ACTION_COUNT_KEYS)
                    or any(type(value) is not int or value < 0 for value in action_counts.values())
                    or sum(action_counts.values()) != block[f"{prefix}_decisions"]
                ):
                    raise ValueError("raw benchmark action counts are inconsistent")
            if block["execution_binding_sha256"] != execution["binding_sha256"]:
                raise ValueError("raw benchmark block is detached from execution binding")
            for transcript_field in (
                "candidate_transcript_sha256",
                "baseline_transcript_sha256",
            ):
                transcript = block[transcript_field]
                if (
                    not isinstance(transcript, str)
                    or len(transcript) != 64
                    or any(character not in "0123456789abcdef" for character in transcript)
                ):
                    raise ValueError("raw benchmark transcript digest is invalid")
            if block["hands"] < MIN_HANDS_PER_BLOCK or block["decisions"] <= 0:
                raise ValueError("raw benchmark block is below the minimum observation volume")
            if block["hands"] % (cell.table_size * cell.table_size) != 0:
                raise ValueError("raw benchmark block does not balance seat and button")
            if type(block["big_blind"]) is not int or block["big_blind"] <= 0:
                raise ValueError("raw benchmark blind is invalid")
            for result_field in ("candidate_chips_delta", "baseline_chips_delta"):
                if type(block[result_field]) is not int:
                    raise ValueError("raw benchmark chip delta is invalid")
            if block_id != _block_identity(cell, block):
                raise ValueError("raw benchmark block identity does not bind its content")
            block_ids.add(block_id)
            delta = (
                (block["candidate_chips_delta"] - block["baseline_chips_delta"])
                / block["big_blind"]
                / block["hands"]
                * 100.0
            )
            if not math.isfinite(delta):
                raise ValueError("raw benchmark delta is non-finite")
            deltas.append(delta)
            blocks += 1
            hands += block["hands"]
            decisions += block["decisions"]
            illegal += block["illegal_actions"]
            non_finite += block["non_finite_outputs"]
            fallbacks += block["fallbacks"]
        observed[cell] = tuple(deltas)
    if set(observed) != expected:
        raise ValueError("raw benchmark panel is incomplete")

    ordered_values = tuple(observed[cell] for cell in preregistered_cells())
    evidence = _analyze_frozen_cells(ordered_values)
    intervals = [(item.estimate_bb100, *item.simultaneous_ci95) for item in evidence]
    aggregate = (
        fmean(item.estimate_bb100 for item in evidence),
        fmean(item.simultaneous_ci95[0] for item in evidence),
        fmean(item.simultaneous_ci95[1] for item in evidence),
    )
    worst = min(intervals, key=lambda interval: interval[1])
    return RawBenchmarkSummary(
        hands=hands,
        decisions=decisions,
        blocks=blocks,
        illegal_actions=illegal,
        non_finite_outputs=non_finite,
        fallbacks=fallbacks,
        aggregate=aggregate,
        worst_cell=worst,
        max_ci_half_width=max((upper - lower) / 2.0 for _, lower, upper in intervals),
        max_holm_adjusted_p_value=max(item.holm_adjusted_p_value for item in evidence),
        execution_binding_sha256=execution["binding_sha256"],
    )
