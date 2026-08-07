"""O contrato `Bot` — todo cérebro implementa o mesmo protocolo."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..engine.actions import Action
from .insight import BotInsight
from .observation import Observation


@runtime_checkable
class Bot(Protocol):
    name: str

    def act(self, obs: Observation) -> Action:
        """Recebe a observação filtrada e devolve uma ação legal."""
        ...


@runtime_checkable
class Explainable(Protocol):
    """Capacidade OPCIONAL: expor o raciocínio da última decisão (glass-box)."""

    def insight(self) -> BotInsight | None: ...
