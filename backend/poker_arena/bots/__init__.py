"""Bots e o contrato que todos compartilham.

Todo bot recebe apenas uma `Observation` filtrada por assento (nunca as cartas de
outros jogadores) e devolve uma `Action` legal. É o que permite o Modo Laboratório:
qualquer cérebro (Random, Heurística, Monte Carlo, NFSP, Deep CFR, PPO) pluga em
qualquer cadeira.
"""

from .base import Bot
from .heuristic_bot import HeuristicBot
from .monte_carlo_bot import MonteCarloBot
from .observation import Observation, PublicPlayer, as_strategy, observation_for
from .random_bot import RandomBot

__all__ = [
    "Bot",
    "HeuristicBot",
    "MonteCarloBot",
    "Observation",
    "PublicPlayer",
    "RandomBot",
    "as_strategy",
    "observation_for",
]
