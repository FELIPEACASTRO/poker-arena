import pytest

from poker_arena.engine.actions import Action, ActionType
from poker_arena.engine.game import Hand, IllegalActionError
from poker_arena.engine.player import Player, PlayerStatus


def _players(n=6, stack=1000):
    return [Player(f"P{i}", stack) for i in range(n)]


def test_legal_actions_preflop_utg():
    h = Hand(_players(), button=0, small_blind=10, big_blind=20, seed=1)
    h.start()
    legal = h.legal_actions()
    assert ActionType.CHECK not in legal  # deve 20 ao BB
    assert ActionType.CALL in legal
    assert ActionType.FOLD in legal
    assert ActionType.RAISE in legal
    assert ActionType.ALL_IN in legal
    assert h.amount_to_call() == 20
    assert h.min_raise_to() == 40  # BB(20) + min_raise(20)


def test_raise_updates_current_bet_and_min_raise():
    h = Hand(_players(), button=0, small_blind=10, big_blind=20, seed=1)
    h.start()
    seat = h.to_act
    h.apply(Action(ActionType.RAISE, amount=60))
    assert h.current_bet == 60
    assert h.players[seat].current_bet == 60
    assert h.players[seat].stack == 940
    assert h.min_raise == 40  # incremento 60 - 20
    assert h.min_raise_to() == 100  # próximo raise precisa chegar a 100


def test_raise_reopens_action_for_those_who_already_acted():
    h = Hand(_players(), button=0, small_blind=10, big_blind=20, seed=1)
    h.start()
    h.apply(Action(ActionType.CALL))  # seat 3
    h.apply(Action(ActionType.CALL))  # seat 4
    h.apply(Action(ActionType.RAISE, amount=60))  # seat 5 aumenta
    assert not h.round_complete()  # 3 e 4 precisam responder ao raise


def test_check_facing_a_bet_is_illegal():
    h = Hand(_players(), button=0, small_blind=10, big_blind=20, seed=1)
    h.start()
    with pytest.raises(IllegalActionError):
        h.apply(Action(ActionType.CHECK))  # UTG deve 20


def test_raise_below_minimum_is_illegal():
    h = Hand(_players(), button=0, small_blind=10, big_blind=20, seed=1)
    h.start()
    with pytest.raises(IllegalActionError):
        h.apply(Action(ActionType.RAISE, amount=30))  # mínimo é 40


def test_short_stack_cannot_raise_must_all_in():
    players = _players()
    players[3].stack = 30  # UTG não alcança o min-raise (40)
    h = Hand(players, button=0, small_blind=10, big_blind=20, seed=1)
    h.start()
    legal = h.legal_actions()
    assert ActionType.RAISE not in legal
    assert ActionType.ALL_IN in legal
    with pytest.raises(IllegalActionError):
        h.apply(Action(ActionType.RAISE, amount=30))


def test_all_in_below_min_raise_is_allowed_but_not_a_full_raise():
    players = _players()
    players[3].stack = 30
    h = Hand(players, button=0, small_blind=10, big_blind=20, seed=1)
    h.start()
    h.apply(Action(ActionType.ALL_IN))  # all-in de 30 (curto)
    assert players[3].stack == 0
    assert players[3].status == PlayerStatus.ALL_IN
    assert h.current_bet == 30  # a aposta a pagar subiu para 30
    assert h.min_raise == 20  # mas NÃO foi um raise cheio (incremento 10 < 20)


# ---- TDA 47 / WSOP 96: all-in incompleto NÃO reabre a aposta ----
def test_short_all_in_does_not_reopen_for_those_who_acted():
    # 3-handed: botão=0 -> SB=1, BB=2; pré-flop começa no seat 0 (botão)
    players = [Player("A", 1000), Player("B", 1000), Player("C", 80)]
    h = Hand(players, button=0, small_blind=10, big_blind=20, seed=1)
    h.start()
    assert h.to_act == 0
    h.apply(Action(ActionType.RAISE, amount=60))  # A aumenta p/ 60 (min_raise=40)
    assert h.to_act == 1
    h.apply(Action(ActionType.CALL))  # B paga 60 (JÁ AGIU)
    assert h.to_act == 2
    h.apply(Action(ActionType.ALL_IN))  # C all-in p/ 80 (incremento 20 < 40 = curto)
    assert h.current_bet == 80
    assert h.min_raise == 40  # não virou aumento cheio
    # volta pro A, que JÁ agiu e enfrenta um all-in curto -> só paga ou desiste
    assert h.to_act == 0
    legal = h.legal_actions()
    assert ActionType.CALL in legal
    assert ActionType.FOLD in legal
    assert ActionType.RAISE not in legal
    assert ActionType.ALL_IN not in legal  # all-in seria um aumento -> proibido aqui


def test_full_all_in_reopens_for_those_who_acted():
    players = [Player("A", 1000), Player("B", 1000), Player("C", 200)]
    h = Hand(players, button=0, small_blind=10, big_blind=20, seed=1)
    h.start()
    h.apply(Action(ActionType.RAISE, amount=60))  # A aumenta p/ 60 (min_raise=40)
    h.apply(Action(ActionType.CALL))  # B paga 60
    h.apply(Action(ActionType.ALL_IN))  # C all-in p/ 200 (incremento 140 >= 40 = CHEIO)
    assert h.current_bet == 200
    assert h.min_raise == 140
    # ação REABERTA -> A (que já agiu) pode reaumentar
    assert h.to_act == 0
    assert ActionType.RAISE in h.legal_actions()


def test_cumulative_short_all_ins_reopen_after_a_full_raise_increment():
    # Ordem preflop com button=3: A(seat2), B(seat3), C(seat0), D(seat1).
    players = [
        Player("C", 180),
        Player("D", 1000),
        Player("A", 1000),
        Player("B", 140),
    ]
    h = Hand(players, button=3, small_blind=10, big_blind=20, seed=1)
    h.start()
    h.apply(Action(ActionType.RAISE, amount=100))  # aumento cheio de 80
    h.apply(Action(ActionType.ALL_IN))  # B: +40, curto
    h.apply(Action(ActionType.ALL_IN))  # C: +40, acumulado +80
    h.apply(Action(ActionType.CALL))  # D paga; volta para A

    assert h.to_act == 2
    assert h.current_bet == 180
    assert h.min_raise == 80
    assert ActionType.RAISE in h.legal_actions()
    assert h.min_raise_to() == 260
