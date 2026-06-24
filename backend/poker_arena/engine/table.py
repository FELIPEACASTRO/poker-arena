"""Mesa: orquestra várias mãos seguidas até sobrar um único jogador com fichas.

É a camada de *sessão* sobre o motor de uma mão (`Hand`): cuida da rotação do
botão, de tirar quem zerou o stack e de saber quando o jogo acabou. É o que
permite medir "a IA vence os baselines em N mãos".
"""

from __future__ import annotations

from .cards import make_rng
from .game import Hand, Strategy
from .player import Player


class Table:
    def __init__(
        self,
        players: list[Player],
        small_blind: int,
        big_blind: int,
        seed: int | None = None,
    ):
        self.players = players
        self.sb = small_blind
        self.bb = big_blind
        self.button = 0
        self._seed = seed
        self._rng = make_rng(seed)
        self.hand_count = 0
        self._last_seated = 0

    def players_with_chips(self) -> list[Player]:
        return [p for p in self.players if p.stack > 0]

    def is_over(self) -> bool:
        return len(self.players_with_chips()) <= 1

    def start_hand(self) -> Hand:
        """Prepara e inicia uma mão SEM jogá-la (caller dirige as ações)."""
        seated = self.players_with_chips()
        if len(seated) <= 1:
            raise RuntimeError("o jogo já acabou — não há mãos a jogar")
        for p in seated:
            p.reset_for_new_hand()
        self._last_seated = len(seated)
        hand = Hand(
            seated,
            button=self.button % len(seated),
            small_blind=self.sb,
            big_blind=self.bb,
            # produção (sem seed): cada mão usa entropia do SO (cripto, imprevisível)
            seed=None if self._seed is None else self._rng.randrange(1 << 30),
        )
        hand.start()
        return hand

    def end_hand(self) -> None:
        """Fecha a mão: conta e anda o botão."""
        self.hand_count += 1
        self.button = (self.button + 1) % max(self._last_seated, 1)

    def play_hand(self, strategy: Strategy) -> tuple[Hand, list[Player]]:
        """Joga uma mão inteira automaticamente (bots) — atalho de start+play+end."""
        hand = self.start_hand()
        winners = hand.play_out(strategy)
        self.end_hand()
        return hand, winners

    def play_until_winner(
        self, strategy: Strategy, max_hands: int = 10_000
    ) -> Player | None:
        while not self.is_over() and self.hand_count < max_hands:
            self.play_hand(strategy)
        survivors = self.players_with_chips()
        return survivors[0] if len(survivors) == 1 else None
