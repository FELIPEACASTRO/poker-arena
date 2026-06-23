"""Máquina de estado de uma mão de Texas Hold'em No-Limit.

Orquestra botão/blinds, distribuição, rodadas de aposta e progressão do board.
Não conhece bots nem rede — só as regras do jogo.
"""

from __future__ import annotations

from .actions import Action, ActionType
from .cards import Card, Deck
from .player import Player, PlayerStatus


class Hand:
    def __init__(
        self,
        players: list[Player],
        button: int,
        small_blind: int,
        big_blind: int,
        seed: int | None = None,
    ):
        self.players = players
        self.button = button
        self.sb = small_blind
        self.bb = big_blind
        self.deck = Deck(seed)
        self.board: list[Card] = []
        self.pot = 0
        self.to_act = 0
        self.current_bet = 0

    # ---- helpers de assento ----
    def _next_seat(self, seat: int) -> int:
        return (seat + 1) % len(self.players)

    def _first_active_from(self, seat: int) -> int:
        for _ in range(len(self.players)):
            if self.players[seat].status == PlayerStatus.ACTIVE:
                return seat
            seat = self._next_seat(seat)
        return seat  # ninguém ativo (todos all-in/folded)

    # ---- início da mão ----
    def start(self) -> None:
        self.deck.shuffle()
        sb_seat = self._next_seat(self.button)
        bb_seat = self._next_seat(sb_seat)
        self._post(sb_seat, self.sb)
        self._post(bb_seat, self.bb)
        self.current_bet = self.bb
        for _ in range(2):  # duas hole cards por jogador
            for p in self.players:
                p.hole.extend(self.deck.deal(1))
        self.to_act = self._first_active_from(self._next_seat(bb_seat))

    def _post(self, seat: int, amount: int) -> None:
        self.pot += self.players[seat].bet(amount)

    # ---- rodada de aposta ----
    def apply(self, action: Action) -> None:
        p = self.players[self.to_act]
        if action.type == ActionType.FOLD:
            p.fold()
        elif action.type == ActionType.CHECK:
            pass
        elif action.type == ActionType.CALL:
            self.pot += p.bet(self.current_bet - p.current_bet)
        elif action.type in (ActionType.RAISE, ActionType.ALL_IN):
            self.pot += p.bet(action.amount - p.current_bet)
            self.current_bet = max(self.current_bet, p.current_bet)
        p.acted = True
        self._advance()

    def _advance(self) -> None:
        self.to_act = self._first_active_from(self._next_seat(self.to_act))

    def round_complete(self) -> bool:
        contesting = [p for p in self.players if p.status != PlayerStatus.FOLDED]
        if len(contesting) <= 1:
            return True
        active = [p for p in self.players if p.status == PlayerStatus.ACTIVE]
        if not active:
            return True  # todos os contestantes estão all-in
        return all(p.acted and p.current_bet == self.current_bet for p in active)

    # ---- progressão do board ----
    def advance_street(self) -> None:
        n = 3 if len(self.board) == 0 else 1  # flop=3, turn/river=1
        self.board.extend(self.deck.deal(n))
        self.current_bet = 0
        for p in self.players:
            p.reset_for_new_round()
        self.to_act = self._first_active_from(self._next_seat(self.button))
