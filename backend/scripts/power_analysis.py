"""Reproduce the minimum-sample design behind the external vision gate."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass

Z_95 = 1.959963984540054


@dataclass(frozen=True, slots=True)
class BinomialDesign:
    samples: int
    critical_events: int
    null_probability: float
    target_probability: float
    type_one_error: float
    power: float


def wilson_bound(events: int, total: int, *, upper: bool) -> float:
    probability = events / total
    denominator = 1 + Z_95**2 / total
    center = (probability + Z_95**2 / (2 * total)) / denominator
    margin = (
        Z_95
        * math.sqrt(
            probability * (1 - probability) / total
            + Z_95**2 / (4 * total**2)
        )
        / denominator
    )
    return min(1.0, center + margin) if upper else max(0.0, center - margin)


def _binomial_tail(events: int, total: int, probability: float, *, upper: bool) -> float:
    values = range(events, total + 1) if upper else range(events + 1)
    return sum(
        math.comb(total, value)
        * probability**value
        * (1 - probability) ** (total - value)
        for value in values
    )


def lower_bound_design(
    *,
    floor: float,
    null_probability: float,
    target_probability: float,
    alpha: float = 0.05,
    target_power: float = 0.80,
) -> BinomialDesign:
    for total in range(1, 2_001):
        critical = next(
            (
                events
                for events in range(total + 1)
                if wilson_bound(events, total, upper=False) >= floor
            ),
            None,
        )
        if critical is None:
            continue
        type_one = _binomial_tail(critical, total, null_probability, upper=True)
        power = _binomial_tail(critical, total, target_probability, upper=True)
        if type_one <= alpha and power >= target_power:
            return BinomialDesign(
                total,
                critical,
                null_probability,
                target_probability,
                type_one,
                power,
            )
    raise RuntimeError("no bounded lower-confidence design satisfies the targets")


def upper_bound_design(
    *,
    ceiling: float,
    null_probability: float,
    target_probability: float,
    alpha: float = 0.05,
    target_power: float = 0.80,
) -> BinomialDesign:
    for total in range(1, 2_001):
        candidates = [
            events
            for events in range(total + 1)
            if wilson_bound(events, total, upper=True) <= ceiling
        ]
        if not candidates:
            continue
        critical = max(candidates)
        type_one = _binomial_tail(critical, total, null_probability, upper=False)
        power = _binomial_tail(critical, total, target_probability, upper=False)
        if type_one <= alpha and power >= target_power:
            return BinomialDesign(
                total,
                critical,
                null_probability,
                target_probability,
                type_one,
                power,
            )
    raise RuntimeError("no bounded upper-confidence design satisfies the targets")


def designs() -> dict[str, BinomialDesign]:
    return {
        "exact_state": lower_bound_design(
            floor=0.90,
            null_probability=0.90,
            target_probability=0.97,
        ),
        "false_accept": upper_bound_design(
            ceiling=0.05,
            null_probability=0.05,
            target_probability=0.01,
        ),
        "subgroup_exact_state": lower_bound_design(
            floor=0.80,
            null_probability=0.80,
            target_probability=0.95,
        ),
    }


def main() -> int:
    print(json.dumps({name: asdict(value) for name, value in designs().items()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
