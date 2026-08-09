"""Secondary solver-labelled evaluation for the Expert v2 policy."""

from __future__ import annotations

import csv
import hashlib
import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Final

from poker_arena.bots.observation import Observation
from poker_arena.ml.action_space_v2 import N_ACTIONS_V2
from poker_arena.ml.pokerbench import featurize_v2

MAX_CSV_BYTES: Final = 16 * 1024 * 1024
Predictor = Callable[[Observation], list[float]]


@dataclass(frozen=True, slots=True)
class PokerBenchEvaluation:
    rows: int
    eligible: int
    ambiguous_sizing: int
    parse_failures: int
    modal_accuracy: float
    modal_accuracy_wilson95: tuple[float, float]
    top3_accuracy: float
    mean_target_probability: float
    cross_entropy: float
    brier: float


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _wilson(successes: int, total: int) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 1.0
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1.0 + z * z / total
    center = (proportion + z * z / (2.0 * total)) / denominator
    spread = (
        z
        * math.sqrt(proportion * (1.0 - proportion) / total + z * z / (4.0 * total * total))
        / denominator
    )
    return max(0.0, center - spread), min(1.0, center + spread)


def _probabilities(value: object) -> list[float]:
    if not isinstance(value, list) or len(value) != N_ACTIONS_V2:
        raise ValueError("PokerBench predictor must return ten probabilities")
    parsed = [float(item) for item in value]
    if any(not math.isfinite(item) or item < 0.0 for item in parsed):
        raise ValueError("PokerBench predictor returned an invalid distribution")
    if not math.isclose(sum(parsed), 1.0, rel_tol=1e-7, abs_tol=1e-9):
        raise ValueError("PokerBench predictor distribution is not normalized")
    return parsed


def evaluate_pokerbench_csv(
    path: Path,
    *,
    expected_sha256: str,
    predictor: Predictor,
) -> PokerBenchEvaluation:
    """Evaluate unambiguous rows; parsing/mapping failures remain visible."""

    if not path.is_file() or path.stat().st_size > MAX_CSV_BYTES:
        raise ValueError("PokerBench CSV is absent or exceeds the bounded test size")
    if (
        len(expected_sha256) != 64
        or any(character not in "0123456789abcdef" for character in expected_sha256.lower())
        or _sha256(path) != expected_sha256.lower()
    ):
        raise ValueError("PokerBench CSV digest mismatch")
    rows = eligible = ambiguous = failures = correct = top3 = 0
    target_probabilities: list[float] = []
    cross_entropies: list[float] = []
    briers: list[float] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError("PokerBench CSV header is absent or duplicated")
        for row in reader:
            rows += 1
            try:
                example = featurize_v2(dict(row))
            except (KeyError, StopIteration, TypeError, ValueError):
                failures += 1
                continue
            if example.mapping_ambiguous:
                ambiguous += 1
                continue
            probabilities = _probabilities(predictor(example.observation))
            target = example.target_index
            modal = max(range(N_ACTIONS_V2), key=probabilities.__getitem__)
            ranking = sorted(range(N_ACTIONS_V2), key=probabilities.__getitem__, reverse=True)
            eligible += 1
            correct += modal == target
            top3 += target in ranking[:3]
            target_probability = probabilities[target]
            target_probabilities.append(target_probability)
            cross_entropies.append(-math.log(max(target_probability, 1e-15)))
            briers.append(
                sum(
                    (probability - (1.0 if index == target else 0.0)) ** 2
                    for index, probability in enumerate(probabilities)
                )
            )
    if eligible == 0:
        raise ValueError("PokerBench mapping produced no unambiguous evaluable rows")
    return PokerBenchEvaluation(
        rows=rows,
        eligible=eligible,
        ambiguous_sizing=ambiguous,
        parse_failures=failures,
        modal_accuracy=correct / eligible,
        modal_accuracy_wilson95=_wilson(correct, eligible),
        top3_accuracy=top3 / eligible,
        mean_target_probability=fmean(target_probabilities),
        cross_entropy=fmean(cross_entropies),
        brier=fmean(briers),
    )
