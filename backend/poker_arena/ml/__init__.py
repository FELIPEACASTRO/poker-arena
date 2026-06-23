"""Ponte entre o motor e políticas neurais (treino + inferência).

`encoder` codifica a `Observation` num vetor de tamanho fixo e mapeia a escolha
discreta da rede numa `Action` legal. É a base da IA treinada (nível Expert).
"""

from .encoder import (
    ACTIONS,
    FEATURE_SIZE,
    N_ACTIONS,
    encode,
    legal_mask,
    to_action,
)
from .self_play_env import OpponentPolicy, SelfPlayEnv, random_opponent

__all__ = [
    "ACTIONS",
    "FEATURE_SIZE",
    "N_ACTIONS",
    "OpponentPolicy",
    "SelfPlayEnv",
    "encode",
    "legal_mask",
    "random_opponent",
    "to_action",
]
