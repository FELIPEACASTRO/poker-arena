"""Política de decisão compartilhada: traduz um sinal de força/equity em ação legal.

Tanto o HeuristicBot (força heurística) quanto o MonteCarloBot (equity simulada)
usam esta mesma lógica de pot odds → garante decisões coerentes e DRY.
"""

from __future__ import annotations

from ..engine.actions import Action, ActionType
from .observation import Observation


def _own_max_raise_to(obs: Observation) -> int:
    me = next(p for p in obs.players if p.seat == obs.seat)
    return me.current_bet + me.stack


def raise_size(obs: Observation) -> int:
    """Aumento ~tamanho do pote, sempre dentro dos limites legais."""
    target = obs.current_bet + obs.pot
    lo, hi = obs.min_raise_to, _own_max_raise_to(obs)
    return max(lo, min(target, hi))


def decide_from_equity(
    obs: Observation, equity: float, raise_threshold: float = 0.75
) -> Action:
    """Decide a ação a partir de uma estimativa de equity em [0, 1]."""
    legal = obs.legal_actions
    want_raise = equity >= raise_threshold and ActionType.RAISE in legal

    if obs.to_call == 0:  # podemos dar check de graça
        if want_raise:
            return Action(ActionType.RAISE, amount=raise_size(obs))
        return Action(ActionType.CHECK)

    # há aposta a pagar: compara equity com pot odds
    pot_odds = obs.to_call / (obs.pot + obs.to_call)
    if want_raise:
        return Action(ActionType.RAISE, amount=raise_size(obs))
    if equity >= pot_odds and ActionType.CALL in legal:
        return Action(ActionType.CALL)
    return Action(ActionType.FOLD)
