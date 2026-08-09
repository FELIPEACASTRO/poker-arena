"""Canonical ten-action abstraction for the next Expert generation.

The module is intentionally separate from encoder v1: the quarantined 121x5
artifact must never be made compatible by merely relabeling its tensors.
"""

from __future__ import annotations

from typing import Final

from poker_arena.bots.observation import Observation, PublicPlayer
from poker_arena.engine.actions import Action, ActionType

REVISION: Final = "poker-arena-actions-v2-2026-08-08"
ACTIONS_V2: Final = (
    "fold",
    "check_call",
    "raise_min",
    "raise_033_pot",
    "raise_050_pot",
    "raise_075_pot",
    "raise_100_pot",
    "raise_150_pot",
    "raise_200_pot",
    "all_in",
)
N_ACTIONS_V2: Final = len(ACTIONS_V2)
_FRACTIONS: Final = {
    3: (1, 3),
    4: (1, 2),
    5: (3, 4),
    6: (1, 1),
    7: (3, 2),
    8: (2, 1),
}


def _hero(obs: Observation) -> PublicPlayer:
    matches = [player for player in obs.players if player.seat == obs.seat]
    if len(matches) != 1:
        raise ValueError("observation must contain the hero exactly once")
    return matches[0]


def _raise_targets(obs: Observation) -> dict[int, int]:
    """Return one unique, legal raise-to target per enabled abstraction."""

    if ActionType.RAISE not in obs.legal_actions:
        return {}
    hero = _hero(obs)
    max_to = hero.current_bet + hero.stack
    if obs.min_raise_to >= max_to:
        return {}
    targets: dict[int, int] = {2: obs.min_raise_to}
    used = {obs.min_raise_to}
    call_cost = min(obs.to_call, hero.stack)
    pot_after_call = obs.pot + call_cost
    for index, (numerator, denominator) in _FRACTIONS.items():
        rounded_bet = (numerator * pot_after_call + denominator // 2) // denominator
        target = obs.current_bet + rounded_bet
        if target < obs.min_raise_to or target >= max_to or target in used:
            continue
        targets[index] = target
        used.add(target)
    return targets


def legal_mask_v2(obs: Observation) -> list[bool]:
    """Mask aliases, undersized raises and implicit all-ins before inference."""

    targets = _raise_targets(obs)
    legal = obs.legal_actions
    return [
        ActionType.FOLD in legal,
        ActionType.CHECK in legal or ActionType.CALL in legal,
        *(index in targets for index in range(2, 9)),
        ActionType.ALL_IN in legal,
    ]


def to_action_v2(obs: Observation, action_index: int) -> Action:
    """Map an unmasked v2 index to exactly one engine action."""

    if type(action_index) is not int:
        raise TypeError("action_index must be an int")
    if not 0 <= action_index < N_ACTIONS_V2:
        raise ValueError(f"action_index must be in [0, {N_ACTIONS_V2})")
    mask = legal_mask_v2(obs)
    if not mask[action_index]:
        raise ValueError("action_index is masked for this observation")
    if action_index == 0:
        return Action(ActionType.FOLD)
    if action_index == 1:
        action_type = ActionType.CHECK if ActionType.CHECK in obs.legal_actions else ActionType.CALL
        return Action(action_type)
    if action_index == 9:
        return Action(ActionType.ALL_IN)
    return Action(ActionType.RAISE, _raise_targets(obs)[action_index])
