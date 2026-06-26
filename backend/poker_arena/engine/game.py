"""Máquina de estado de uma mão de Texas Hold'em No-Limit.

Orquestra botão/blinds, distribuição, rodadas de aposta (com validação de
legalidade e regras de No-Limit) e progressão do board. Não conhece bots nem
rede — só as regras do jogo.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .actions import Action, ActionType
from .cards import Card, Deck
from .evaluator import evaluate
from .player import Player, PlayerStatus


class IllegalActionError(ValueError):
    """A ação não é válida para o estado atual da mão."""


# Uma estratégia decide a ação do jogador da vez.
Strategy = Callable[["Hand"], Action]


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
        self.pot = 0  # só para exibição; a resolução usa total_committed
        self.to_act = 0
        self.current_bet = 0
        self.min_raise = big_blind  # incremento mínimo de um raise

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
        heads_up = len(self.players) == 2
        if heads_up:  # no HU, o botão é a small blind
            sb_seat = self.button
            bb_seat = self._next_seat(self.button)
        else:
            sb_seat = self._next_seat(self.button)
            bb_seat = self._next_seat(sb_seat)
        self._post(sb_seat, self.sb)
        self._post(bb_seat, self.bb)
        self.current_bet = self.bb
        self.min_raise = self.bb
        # distribui uma a uma, começando pelo SB (esquerda do botão) — ordem oficial
        n = len(self.players)
        order = [self.players[(sb_seat + k) % n] for k in range(n)]
        for _ in range(2):  # duas hole cards por jogador
            for p in order:
                p.hole.extend(self.deck.deal(1))
        # preflop: HU -> botão/SB age primeiro; senão -> esquerda do BB (UTG)
        first = sb_seat if heads_up else self._next_seat(bb_seat)
        self.to_act = self._first_active_from(first)

    def _post(self, seat: int, amount: int) -> None:
        self.pot += self.players[seat].bet(amount)

    # ---- consultas de aposta ----
    def amount_to_call(self) -> int:
        return self.current_bet - self.players[self.to_act].current_bet

    def min_raise_to(self) -> int:
        """Menor 'total nesta rodada' para um raise voluntário válido."""
        return self.current_bet + self.min_raise

    def legal_actions(self) -> set[ActionType]:
        p = self.players[self.to_act]
        to_call = self.amount_to_call()
        actions: set[ActionType] = {ActionType.FOLD}
        if to_call == 0:
            actions.add(ActionType.CHECK)
        if to_call > 0 and p.stack > 0:
            actions.add(ActionType.CALL)
        # a ação só está ABERTA pra aumentar se o jogador ainda não agiu nesta
        # "rodada de aumentos". Um all-in curto (< aumento cheio) NÃO reabre a aposta
        # pra quem já agiu — regra TDA 47 / WSOP 96 (ele só pode pagar ou desistir).
        reopened = not p.acted
        if reopened and p.stack > to_call and (p.current_bet + p.stack) >= self.min_raise_to():
            actions.add(ActionType.RAISE)
        # all-in: vale sempre como PAGAMENTO; como AUMENTO, só se a ação está aberta
        if p.stack > 0 and (reopened or p.stack <= to_call):
            actions.add(ActionType.ALL_IN)
        return actions

    def _reopen_betting(self) -> None:
        """Um aumento CHEIO reabre a aposta: os demais ativos voltam a poder agir
        (inclusive reaumentar). Curtos all-ins incompletos NÃO chamam isto."""
        for i, p in enumerate(self.players):
            if i != self.to_act and p.status == PlayerStatus.ACTIVE:
                p.acted = False

    # ---- aplicar ação ----
    def apply(self, action: Action) -> None:
        if action.type not in self.legal_actions():
            raise IllegalActionError(
                f"{action.type} ilegal; legais: {self.legal_actions()}"
            )
        p = self.players[self.to_act]
        if action.type == ActionType.FOLD:
            p.fold()
        elif action.type == ActionType.CHECK:
            pass
        elif action.type == ActionType.CALL:
            self.pot += p.bet(self.amount_to_call())
        elif action.type == ActionType.RAISE:
            self._apply_raise(action.amount)
        elif action.type == ActionType.ALL_IN:
            self._apply_all_in()
        p.acted = True
        self._advance()

    def _apply_raise(self, raise_to: int) -> None:
        p = self.players[self.to_act]
        max_to = p.current_bet + p.stack
        if raise_to > max_to:
            raise IllegalActionError("raise acima do stack disponível; use ALL_IN")
        if raise_to < self.min_raise_to():
            raise IllegalActionError(
                f"raise mínimo é {self.min_raise_to()} (recebido {raise_to})"
            )
        self.min_raise = raise_to - self.current_bet
        self.pot += p.bet(raise_to - p.current_bet)
        self.current_bet = p.current_bet
        self._reopen_betting()  # aumento voluntário é sempre cheio -> reabre a aposta

    def _apply_all_in(self) -> None:
        p = self.players[self.to_act]
        prev = self.current_bet
        self.pot += p.bet(p.stack)  # aposta todo o stack
        if p.current_bet > prev:  # all-in que age como raise
            increment = p.current_bet - prev
            if increment >= self.min_raise:  # raise CHEIO -> reabre a aposta
                self.min_raise = increment
                self._reopen_betting()
            self.current_bet = p.current_bet
            # all-in curto (< aumento cheio) NÃO reabre: quem já agiu só paga/desiste

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
        self._deal_board()
        self.current_bet = 0
        self.min_raise = self.bb
        for p in self.players:
            p.reset_for_new_round()
        self.to_act = self._first_active_from(self._next_seat(self.button))

    def _deal_board(self) -> None:
        n = 3 if len(self.board) == 0 else 1  # flop=3, turn/river=1
        self.deck.deal(1)  # burn card (descartada antes de cada street) — regra oficial
        self.board.extend(self.deck.deal(n))

    def _runout_board(self) -> None:
        """Completa o board até 5 cartas (showdown com jogadores all-in)."""
        while len(self.board) < 5:
            self._deal_board()

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
        pots = self.build_side_pots()
        # showdown disputado precisa do board completo
        if len(self.board) < 5 and any(len(pot.eligible) > 1 for pot in pots):
            self._runout_board()
        all_winners: list[Player] = []
        n = len(self.players)
        for pot in pots:
            pot_winners = self._winners_of(pot.eligible)
            # ficha(s) ímpar(es): uma a uma, começando pelo 1º vencedor à ESQUERDA do
            # botão (regra oficial de distribuição da odd chip).
            pot_winners.sort(key=lambda w: (self.players.index(w) - self.button - 1) % n)
            share = pot.amount // len(pot_winners)
            remainder = pot.amount - share * len(pot_winners)
            for idx, w in enumerate(pot_winners):
                w.stack += share + (1 if idx < remainder else 0)
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
    def play_out(self, strategy: Strategy) -> list[Player]:
        """Joga a mão até o fim usando `strategy(hand) -> Action` para cada vez.

        Avança street a street; encerra quando sobra um só contestante ou o river
        termina. Retorna os vencedores (com os stacks já creditados).
        """
        while True:
            guard = 0
            while not self.round_complete():
                if guard >= 1000:
                    raise RuntimeError(
                        "rodada não converge — estratégia gerando ações inválidas?"
                    )
                self.apply(strategy(self))
                guard += 1
            contesting = [p for p in self.players if p.status != PlayerStatus.FOLDED]
            if len(contesting) <= 1 or len(self.board) >= 5:
                break
            self.advance_street()
        return self.resolve()
