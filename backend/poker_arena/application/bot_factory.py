"""Factory de bots (padrão Factory + Open/Closed).

Mapeia um nível textual ("random"/"heuristic"/"montecarlo") na implementação de
`Bot` correspondente. Adicionar um novo cérebro = registrar aqui, sem tocar no
resto. Os bots em si são o padrão Strategy.
"""

from __future__ import annotations

from collections.abc import Callable

from ..bots import HeuristicBot, MonteCarloBot, RandomBot
from ..bots.base import Bot


class UnknownBotLevel(ValueError):
    """Nível de bot não registrado na factory."""


_BUILDERS: dict[str, Callable[[int | None], Bot]] = {
    "random": lambda seed: RandomBot(seed=seed),
    "heuristic": lambda seed: HeuristicBot(seed=seed),
    "montecarlo": lambda seed: MonteCarloBot(seed=seed),
}

LEVELS: tuple[str, ...] = tuple(_BUILDERS)


def create_bot(level: str, seed: int | None = None) -> Bot:
    builder = _BUILDERS.get(level)
    if builder is None:
        raise UnknownBotLevel(f"nível desconhecido: {level!r}; use um de {LEVELS}")
    return builder(seed)
