"""Ambiente de self-play: o motor de poker como um env de RL (reset/step).

Um episódio = uma mão. O **agente** joga uma cadeira; os demais usam uma *policy
oponente* (callable `(obs, mask) -> índice de ação`). A recompensa é a variação de
fichas do agente naquela mão. Sem `gymnasium` aqui (puro e testável); o notebook
de treino embrulha isto numa interface Gym para o PPO.
"""

from __future__ import annotations

import random
from collections.abc import Callable

from ..bots.observation import observation_for
from ..engine.game import Hand
from ..engine.player import Player, PlayerStatus
from .encoder import FEATURE_SIZE, N_ACTIONS, encode, legal_mask, to_action

# (features já codificadas, máscara de ações legais) -> índice da ação discreta.
# O env entrega as FEATURES prontas (não o Observation cru): assim a política
# neural pode ir direto pro predict, sem ninguém esquecer de chamar encode().
OpponentPolicy = Callable[[list[float], list[bool]], int]

StepResult = tuple[list[float], list[bool], float, bool]


def random_opponent(rng: random.Random) -> OpponentPolicy:
    """Oponente que escolhe uniformemente entre as ações legais."""

    def policy(_feats: list[float], mask: list[bool]) -> int:
        return rng.choice([i for i, ok in enumerate(mask) if ok])

    return policy


class SelfPlayEnv:
    def __init__(
        self,
        n_players: int = 6,
        starting_stack: int = 1000,
        small_blind: int = 10,
        big_blind: int = 20,
        opponent: OpponentPolicy | None = None,
        seed: int | None = None,
    ):
        for name, value in (
            ("n_players", n_players),
            ("starting_stack", starting_stack),
            ("small_blind", small_blind),
            ("big_blind", big_blind),
        ):
            if type(value) is not int:
                raise TypeError(f"{name} must be an int")
        if n_players < 2:
            raise ValueError("n_players must be at least 2")
        if starting_stack <= 0:
            raise ValueError("starting_stack must be positive")
        if small_blind <= 0 or big_blind <= small_blind:
            raise ValueError("blinds must satisfy 0 < small_blind < big_blind")
        if big_blind > starting_stack:
            raise ValueError("big_blind cannot exceed starting_stack")
        if opponent is not None and not callable(opponent):
            raise TypeError("opponent must be callable")
        self.n = n_players
        self.stack = starting_stack
        self.sb = small_blind
        self.bb = big_blind
        self._rng = random.Random(seed)  # noqa: S311 - reproducible self-play simulation RNG
        self.opponent: OpponentPolicy = opponent or random_opponent(self._rng)
        self._agent_seat = 0
        self._hands = 0

    def set_opponent(self, opponent: OpponentPolicy) -> None:
        """Troca o oponente (no self-play, vira a própria política em treino)."""
        if not callable(opponent):
            raise TypeError("opponent must be callable")
        self.opponent = opponent

    def reset(self, *, seed: int | None = None) -> tuple[list[float], list[bool]]:
        if seed is not None:
            if type(seed) is not int:
                raise TypeError("seed must be an int")
            self._rng.seed(seed)
            self._hands = 0
        for _ in range(100):  # redeals até o agente ter uma decisão
            players = [Player(f"P{i}", self.stack) for i in range(self.n)]
            self._players = players
            self._agent = players[self._agent_seat]
            self._start = self._agent.stack
            self._hand = Hand(
                players,
                button=self._hands % self.n,
                small_blind=self.sb,
                big_blind=self.bb,
                seed=self._rng.randrange(1 << 30),
            )
            self._hand.start()
            self._hands += 1
            if not self._advance_to_agent():
                obs = observation_for(self._hand)
                return encode(obs), legal_mask(obs)
        raise RuntimeError("não consegui chegar a uma decisão do agente")

    def step(self, action_index: int) -> StepResult:
        obs = observation_for(self._hand)
        self._hand.apply(to_action(obs, action_index))
        if self._advance_to_agent():  # mão acabou
            # recompensa em BIG BLINDS (não em fichas cruas) -> PPO estável
            reward = float(self._agent.stack - self._start) / self.bb
            return [0.0] * FEATURE_SIZE, [False] * N_ACTIONS, reward, True
        nobs = observation_for(self._hand)
        return encode(nobs), legal_mask(nobs), 0.0, False

    # ---- interno ----
    def _advance_to_agent(self) -> bool:
        """Joga os oponentes até a vez do agente. Retorna True se a mão acabou."""
        hand = self._hand
        while True:
            while not hand.round_complete():
                if hand.to_act == self._agent_seat:
                    return False
                obs = observation_for(hand)
                idx = self.opponent(encode(obs), legal_mask(obs))
                hand.apply(to_action(obs, idx))
            contesting = [p for p in hand.players if p.status != PlayerStatus.FOLDED]
            if len(contesting) <= 1 or len(hand.board) >= 5:
                hand.resolve()
                return True
            hand.advance_street()
