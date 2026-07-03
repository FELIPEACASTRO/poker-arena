"""Oráculo de conformidade: nosso motor × PokerKit (U. Toronto, IEEE ToG).

Joga a MESMA mão (mesmas cartas, mesmas ações) no nosso motor e no
`NoLimitTexasHoldem` do pokerkit e exige os MESMOS stacks finais. Cobre
exatamente onde motores próprios erram calados: pote, min-raise, all-in
e side pots multiway.

Convenções casadas (verificadas por sonda):
- pokerkit: índice 0 = small blind, 1 = big blind, último índice = botão.
- nosso motor com button = n-1 produz o mesmo layout (SB=0, BB=1).
"""

from __future__ import annotations

from collections import deque

import pytest

pokerkit = pytest.importorskip("pokerkit")
from pokerkit import Automation, NoLimitTexasHoldem  # noqa: E402

from poker_arena.engine.actions import Action, ActionType  # noqa: E402
from poker_arena.engine.game import Hand  # noqa: E402
from poker_arena.engine.player import Player  # noqa: E402

_AUTOS = (
    Automation.ANTE_POSTING,
    Automation.BET_COLLECTION,
    Automation.BLIND_OR_STRADDLE_POSTING,
    Automation.CARD_BURNING,
    Automation.HOLE_CARDS_SHOWING_OR_MUCKING,
    Automation.HAND_KILLING,
    Automation.CHIPS_PUSHING,
    Automation.CHIPS_PULLING,
)
SB, BB = 10, 20


def _run_ours(stacks: list[int], script: list[Action], seed: int):
    """Roda a mão no NOSSO motor com button = n-1 e um roteiro de ações.

    Retorna (stacks finais, holes por assento, board, timeline p/ replay).
    A timeline traduz cada ação pro vocabulário do pokerkit no MOMENTO em que
    ela ocorre (all-in abaixo do call vira check/call; acima vira raise-to).
    """
    players = [Player(f"P{i}", s) for i, s in enumerate(stacks)]
    hand = Hand(players, button=len(players) - 1, small_blind=SB, big_blind=BB, seed=seed)
    hand.start()
    holes = ["".join(str(c) for c in p.hole) for p in players]

    queue = deque(script)
    timeline: list[tuple[int, str, int | None]] = []

    def strategy(h: Hand) -> Action:
        action = queue.popleft()
        seat = h.to_act
        p = h.players[seat]
        if action.type is ActionType.FOLD:
            timeline.append((seat, "f", None))
        elif action.type in (ActionType.CHECK, ActionType.CALL):
            timeline.append((seat, "cc", None))
        elif action.type is ActionType.RAISE:
            timeline.append((seat, "r", action.amount))
        else:  # ALL_IN: mapeia pela situação REAL no momento da ação
            total = p.current_bet + p.stack
            if total <= h.current_bet:
                timeline.append((seat, "cc", None))  # all-in de call (ou menos)
            else:
                timeline.append((seat, "r", total))
        return action

    hand.play_out(strategy)
    assert not queue, "roteiro tem ações sobrando — cenário mal especificado"
    board = [str(c) for c in hand.board]
    return [p.stack for p in players], holes, board, timeline


def _replay_pokerkit(stacks, holes, board, timeline):
    """Reproduz a mesma mão no pokerkit e devolve os stacks finais."""
    n = len(stacks)
    state = NoLimitTexasHoldem.create_state(
        _AUTOS, True, 0, (SB, BB), BB, tuple(stacks), n
    )
    while state.can_deal_hole():
        state.deal_hole(holes[state.hole_dealee_index])
    q = deque(timeline)
    board_q = deque(board)
    guard = 0
    while state.status and guard < 200:
        guard += 1
        if state.can_deal_board():
            k = state.board_dealing_count
            state.deal_board("".join(board_q.popleft() for _ in range(k)))
        elif state.actor_index is not None and q:
            seat, kind, amount = q.popleft()
            assert state.actor_index == seat, (
                f"ordem de ação divergente: pokerkit espera {state.actor_index}, nós {seat}"
            )
            if kind == "f":
                state.fold()
            elif kind == "cc":
                state.check_or_call()
            else:
                state.complete_bet_or_raise_to(amount)
        else:
            break
    assert not q, "pokerkit não consumiu todas as ações — máquinas divergiram"
    return list(state.stacks)


def _oracle(stacks: list[int], script: list[Action], seed: int) -> None:
    ours, holes, board, timeline = _run_ours(list(stacks), script, seed)
    theirs = _replay_pokerkit(stacks, holes, board, timeline)
    assert ours == theirs, f"stacks divergem: nosso={ours} pokerkit={theirs}"
    assert sum(ours) == sum(stacks)  # conservação de fichas


R, C, F, K, A = (
    lambda x: Action(ActionType.RAISE, amount=x),
    Action(ActionType.CALL),
    Action(ActionType.FOLD),
    Action(ActionType.CHECK),
    Action(ActionType.ALL_IN),
)


def test_oracle_raise_call_to_showdown():
    # 3p: UTG/botão aumenta pra 60, blinds pagam; todos passam até o river
    script = [R(60), C, C] + [K, K, K] * 3
    _oracle([1000, 1000, 1000], script, seed=42)


def test_oracle_bet_and_folds_no_showdown():
    # aposta no flop leva o pote sem showdown
    script = [C, C, K] + [R(40), F, F]
    _oracle([1000, 1000, 1000], script, seed=7)


def test_oracle_short_all_in():
    # botão curtinho vai all-in de 30 (menos que o min-raise); blinds pagam
    script = [A, C, C] + [K, K] * 3
    _oracle([1000, 1000, 30], script, seed=3)


def test_oracle_multiway_all_in_side_pots():
    # 4 stacks diferentes, todos all-in no pré-flop -> main pot + 2 side pots
    script = [R(100), A, A, A, C]
    _oracle([500, 200, 1000, 350], script, seed=11)


def test_oracle_reraise_line():
    # raise -> reraise -> call em 3 vias, depois aposta+fold no flop
    script = [R(60), R(160), C, C] + [R(200), F, C] + [K, K] * 2
    _oracle([1500, 1500, 1500], script, seed=21)
