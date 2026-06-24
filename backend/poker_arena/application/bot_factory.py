"""Factory de bots (padrão Factory + Open/Closed).

Mapeia um nível textual ("random"/"heuristic"/"montecarlo"/"expert") na
implementação de `Bot` correspondente. Adicionar um novo cérebro = registrar aqui,
sem tocar no resto. Os bots em si são o padrão Strategy. O Expert carrega uma
política neural treinada (ONNX) e só fica disponível quando o modelo existe.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from ..bots import HeuristicBot, MonteCarloBot, RandomBot
from ..bots.base import Bot


class UnknownBotLevel(ValueError):
    """Nível de bot não registrado na factory."""


class ExpertUnavailable(RuntimeError):
    """Nível Expert pedido, mas o modelo treinado (.onnx) não está disponível."""


def expert_model_path() -> Path:
    """Onde o backend procura a política treinada. Override via POKER_EXPERT_MODEL."""
    env = os.environ.get("POKER_EXPERT_MODEL")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "models" / "poker_expert.onnx"


def _expert(seed: int | None) -> Bot:
    path = expert_model_path()
    if not path.exists():
        raise ExpertUnavailable(
            f"modelo Expert não encontrado em {path}; treine no notebook 05 e "
            "coloque o poker_expert.onnx lá (ou defina POKER_EXPERT_MODEL)"
        )
    from ..bots.ml_bot import MLBot  # import tardio: onnxruntime só quando usado

    return MLBot(path)


_BUILDERS: dict[str, Callable[[int | None], Bot]] = {
    "random": lambda seed: RandomBot(seed=seed),
    "heuristic": lambda seed: HeuristicBot(seed=seed),
    "montecarlo": lambda seed: MonteCarloBot(seed=seed),
    "expert": _expert,
}

LEVELS: tuple[str, ...] = tuple(_BUILDERS)


def create_bot(level: str, seed: int | None = None) -> Bot:
    builder = _BUILDERS.get(level)
    if builder is None:
        raise UnknownBotLevel(f"nível desconhecido: {level!r}; use um de {LEVELS}")
    return builder(seed)


def available_levels() -> tuple[str, ...]:
    """Níveis utilizáveis agora.

    `adaptive` (aprende o humano) é montado no build_session, não pela factory.
    `expert` só aparece se o modelo treinado existir.
    """
    levels = ["random", "heuristic", "montecarlo", "adaptive"]
    if expert_model_path().exists():
        levels.append("expert")
    return tuple(levels)
