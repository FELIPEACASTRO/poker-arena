"""Versioned, deterministic opponent panel used only by Expert evaluation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Final

from poker_arena.bots.base import Bot
from poker_arena.bots.heuristic_bot import HeuristicBot
from poker_arena.bots.monte_carlo_bot import MonteCarloBot
from poker_arena.bots.observation import Observation
from poker_arena.bots.random_bot import RandomBot
from poker_arena.engine.actions import Action, ActionType

REVISION: Final = "poker-arena-expert-opponents-v1-2026-08-08"
BASELINE_REVISION: Final = "poker-arena-expert-heuristic-baseline-v1-2026-08-08"


class CallingStationBot:
    """Beginner control: never raises and continues whenever a call is legal."""

    name = "CallingStationBot"

    def act(self, obs: Observation) -> Action:
        if ActionType.CHECK in obs.legal_actions:
            return Action(ActionType.CHECK)
        if ActionType.CALL in obs.legal_actions:
            return Action(ActionType.CALL)
        if ActionType.ALL_IN in obs.legal_actions:
            return Action(ActionType.ALL_IN)
        return Action(ActionType.FOLD)


class ManiacBot:
    """Aggression stressor: raises the legal minimum, otherwise continues."""

    name = "ManiacBot"

    def act(self, obs: Observation) -> Action:
        if ActionType.RAISE in obs.legal_actions:
            return Action(ActionType.RAISE, obs.min_raise_to)
        if ActionType.ALL_IN in obs.legal_actions:
            return Action(ActionType.ALL_IN)
        if ActionType.CALL in obs.legal_actions:
            return Action(ActionType.CALL)
        if ActionType.CHECK in obs.legal_actions:
            return Action(ActionType.CHECK)
        return Action(ActionType.FOLD)


_FACTORIES: Final[dict[str, Callable[[int], Bot]]] = {
    "random": lambda seed: RandomBot(seed=seed),
    "calling_station": lambda _seed: CallingStationBot(),
    "nit": lambda seed: HeuristicBot(name="NitControl", seed=seed, raise_threshold=0.90),
    "heuristic": lambda seed: HeuristicBot(seed=seed),
    "montecarlo_300": lambda seed: MonteCarloBot(seed=seed, n_samples=300),
    "maniac": lambda _seed: ManiacBot(),
    "heuristic_tight": lambda seed: HeuristicBot(
        name="TightHeuristicControl", seed=seed, raise_threshold=0.82
    ),
    "montecarlo_1000": lambda seed: MonteCarloBot(seed=seed, n_samples=1_000),
    "montecarlo_3000": lambda seed: MonteCarloBot(seed=seed, n_samples=3_000),
}


def create_benchmark_opponent(name: str, seed: int) -> Bot:
    """Construct exactly one opponent from the frozen evaluation panel."""

    factory = _FACTORIES.get(name)
    if factory is None:
        raise ValueError(f"unknown benchmark opponent: {name!r}")
    return factory(seed)


def create_benchmark_baseline(seed: int) -> Bot:
    """Construct the one frozen baseline allowed by the official runner."""

    return HeuristicBot(name="FrozenHeuristicBaseline", seed=seed, raise_threshold=0.72)


def baseline_policy_sha256() -> str:
    """Bind the baseline revision, explicit parameters and implementation bytes."""

    implementation = Path(__file__).resolve().parents[1] / "bots" / "heuristic_bot.py"
    payload = {
        "revision": BASELINE_REVISION,
        "factory": "HeuristicBot",
        "raise_threshold": 0.72,
        "implementation_sha256": hashlib.sha256(implementation.read_bytes()).hexdigest(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def opponent_names() -> frozenset[str]:
    return frozenset(_FACTORIES)
