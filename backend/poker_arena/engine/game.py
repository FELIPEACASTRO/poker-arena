"""Máquina de estado de uma mão de Texas Hold'em No-Limit.

Orquestra botão/blinds, distribuição, rodadas de aposta e progressão do board.
Não conhece bots nem rede — só as regras do jogo.
"""

from __future__ import annotations

from dataclasses import dataclass

from .actions import Action, ActionType
from .cards import Card, Deck
from .evaluator import evaluate
from .player import Player, PlayerStatus


@dataclass
class Pot:
    """Um pote (principal ou lateral) e os jogadores elegíveis a ganhá-lo."""

    amount: int
    eligible: list[Player]


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

    # ---- resolução (side pots + vencedores) ----
    def build_side_pots(self) -> list[Pot]:
        """Constrói main pot + side pots a partir do total apostado por cada um.

        Algoritmo de camadas: a cada nível de contribuição, fecha-se um pote com
        todos que contribuíram até ali; só os não-foldados são elegíveis.
        """
        remaining = {
            i: p.total_committed
            for i, p in enumerate(self.players)
            if p.total_committed > 0
        }
        pots: list[Pot] = []
        while remaining:
            layer = min(remaining.values())
            contributors = list(remaining.keys())
            amount = layer * len(contributors)
            eligible = [
                self.players[i]
                for i in contributors
                if self.players[i].status != PlayerStatus.FOLDED
            ]
            pots.append(Pot(amount=amount, eligible=eligible))
            for i in contributors:
                remaining[i] -= layer
                if remaining[i] == 0:
                    del remaining[i]
        return pots

    def _winners_of(self, eligible: list[Player]) -> list[Player]:
        if len(eligible) == 1:
            return list(eligible)
        best_score = None
        winners: list[Player] = []
        for p in eligible:
            score = evaluate(p.hole, self.board)  # menor = melhor
            if best_score is None or score < best_score:
                best_score, winners = score, [p]
            elif score == best_score:
                winners.append(p)
        return winners

    def resolve(self) -> list[Player]:
        """Distribui cada pote ao(s) melhor(es) elegível(is). Retorna vencedores."""
        all_winners: list[Player] = []
        for pot in self.build_side_pots():
            pot_winners = self._winners_of(pot.eligible)
            share = pot.amount // len(pot_winners)
            remainder = pot.amount - share * len(pot_winners)
            for idx, w in enumerate(pot_winners):
                w.stack += share + (remainder if idx == 0 else 0)
                all_winners.append(w)
        # dedup preservando ordem (por identidade)
        seen: set[int] = set()
        result: list[Player] = []
        for w in all_winners:
            if id(w) not in seen:
                seen.add(id(w))
                result.append(w)
        return result

    # ---- orquestração de uma mão completa ----
    def play_out(self, strategy) -> list[Player]:
        """Joga a mão até o fim usando `strategy(hand) -> Action` para cada vez.

        Avança street a street; encerra quando sobra um só contestante ou o river
        termina. Retorna os vencedores (com os stacks já creditados).
        """
        while True:
            guard = 0
            while not self.round_complete() and guard < 1000:
                self.apply(strategy(self))
                guard += 1
            contesting = [p for p in self.players if p.status != PlayerStatus.FOLDED]
            if len(contesting) <= 1 or len(self.board) >= 5:
                break
            self.advance_street()
        return self.resolve()
