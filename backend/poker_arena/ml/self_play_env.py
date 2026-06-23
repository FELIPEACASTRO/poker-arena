"""Ambiente de self-play: o motor de poker como um env de RL (reset/step).

Um episódio = uma mão. O **agente** joga uma cadeira; os demais usam uma *policy
oponente* (callable `(obs, mask) -> índice de ação`). A recompensa é a variação de
fichas do agente naquela mão. Sem `gymnasium` aqui (puro e testável); o notebook
de treino embrulha isto numa interface Gym para o PPO.
"""

from __future__ import annotations

import random
from collections.abc import Callable

from ..bots.observation import Observation, observation_for
from ..engine.game import Hand
from ..engine.player import Player, PlayerStatus
from .encoder import FEATURE_SIZE, N_ACTIONS, encode, legal_mask, to_action

# (observação, máscara de ações legais) -> índice da ação discreta
OpponentPolicy = Callable[[Observation, list[bool]], int]

StepResult = tuple[list[float], list[bool], float, bool]


def random_opponent(rng: random.Random) -> OpponentPolicy:
    """Oponente que escolhe uniformemente entre as ações legais."""

    def policy(_obs: Observation, mask: list[bool]) -> int:
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
        self.n = n_players
        self.stack = starting_stack
        self.sb = small_blind
        self.bb = big_blind
        self._rng = random.Random(seed)
        self.opponent: OpponentPolicy = opponent or random_opponent(self._rng)
        self._agent_seat = 0
        self._hands = 0

    def set_opponent(self, opponent: OpponentPolicy) -> None:
        """Troca o oponente (no self-play, vira a própria política em treino)."""
        self.opponent = opponent

    def reset(self) -> tuple[list[float], list[bool]]:
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
        mask = legal_mask(obs)
        if not mask[action_index]:  # ação ilegal -> fallback seguro
            action_index = 1 if mask[1] else 0
        self._hand.apply(to_action(obs, action_index))
        if self._advance_to_agent():  # mão acabou
            reward = float(self._agent.stack - self._start)
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
                hand.apply(to_action(obs, self.opponent(obs, legal_mask(obs))))
            contesting = [p for p in hand.players if p.status != PlayerStatus.FOLDED]
            if len(contesting) <= 1 or len(hand.board) >= 5:
                hand.resolve()
                return True
            hand.advance_street()
