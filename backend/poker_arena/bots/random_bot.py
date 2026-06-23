"""RandomBot — o nível 🟢 Iniciante e a prova de que o contrato funciona.

Escolhe uniformemente entre as ações LEGAIS da observação. Por construção nunca
produz ação ilegal (só enxerga `obs.legal_actions`).
"""

from __future__ import annotations

import random

from ..engine.actions import Action, ActionType
from .observation import Observation


class RandomBot:
    def __init__(self, name: str = "RandomBot", seed: int | None = None):
        self.name = name
        self._rng = random.Random(seed)

    def act(self, obs: Observation) -> Action:
        choice = self._rng.choice(sorted(obs.legal_actions, key=lambda a: a.value))
        if choice == ActionType.RAISE:
            # aposta o mínimo legal (já garantido como <= stack pela legal_actions)
            return Action(ActionType.RAISE, amount=obs.min_raise_to)
        return Action(choice)
