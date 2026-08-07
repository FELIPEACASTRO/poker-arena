from poker_arena.bots._policy import decide_from_equity
from poker_arena.bots.observation import Observation, PublicPlayer
from poker_arena.engine.actions import ActionType
from poker_arena.engine.evaluator import card_from_str


def _short_call_observation() -> Observation:
    players = (
        PublicPlayer(0, "Hero", 30, 20, 20, "active", False),
        PublicPlayer(1, "Villain", 900, 100, 100, "active", True),
    )
    return Observation(
        seat=0,
        hole=(card_from_str("As"), card_from_str("Ah")),
        board=(),
        pot=70,
        to_call=80,
        current_bet=100,
        min_raise_to=180,
        legal_actions=frozenset({ActionType.FOLD, ActionType.ALL_IN}),
        players=players,
        num_active=2,
    )


def test_short_stack_call_uses_real_cost_and_canonical_all_in_action() -> None:
    observation = _short_call_observation()

    assert decide_from_equity(observation, equity=0.31).type == ActionType.ALL_IN
    assert decide_from_equity(observation, equity=0.29).type == ActionType.FOLD
