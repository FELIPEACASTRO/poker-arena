from __future__ import annotations

import pytest

from poker_arena.bots.observation import Observation, PublicPlayer
from poker_arena.engine.actions import ActionType
from poker_arena.engine.evaluator import card_from_str
from poker_arena.ml.benchmark_opponents import create_benchmark_opponent, opponent_names
from poker_arena.ml.expert_benchmark import OPPONENT_PANEL


def _observation(legal: set[ActionType]) -> Observation:
    return Observation(
        seat=0,
        hole=(card_from_str("As"), card_from_str("Kd")),
        board=(),
        pot=30,
        to_call=20,
        current_bet=20,
        min_raise_to=40,
        legal_actions=frozenset(legal),
        players=(
            PublicPlayer(0, "hero", 980, 0, 0, "active", False),
            PublicPlayer(1, "villain", 980, 20, 20, "active", True),
        ),
        num_active=2,
    )


def test_every_preregistered_opponent_has_a_real_factory():
    declared = {name for panel in OPPONENT_PANEL.values() for name in panel}
    assert declared == opponent_names()
    observation = _observation(
        {ActionType.FOLD, ActionType.CALL, ActionType.RAISE, ActionType.ALL_IN}
    )
    for name in sorted(declared):
        action = create_benchmark_opponent(name, seed=7).act(observation)
        assert action.type in observation.legal_actions


def test_unknown_or_fictitious_solver_label_fails_closed():
    with pytest.raises(ValueError, match="unknown benchmark opponent"):
        create_benchmark_opponent("solver_reference", seed=1)
