"""Auditable signals exposed by a bot decision."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BotInsight:
    kind: str
    label: str
    confidence: float
    probs: tuple[float, ...] | None = None
    fold_to_bet: float | None = None
    bias: float | None = None
    modal_action: str | None = None
    modal_probability: float | None = None
    executed_action: str | None = None
    executed_probability: float | None = None
    decision_rule: str | None = None
    policy_entropy: float | None = None
