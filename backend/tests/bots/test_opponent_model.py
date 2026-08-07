"""OpponentModel com prior neutro e fraco, sem atribuir representatividade falsa."""

import pytest

from poker_arena.bots.opponent_model import (
    NEUTRAL_AGGRESSION,
    NEUTRAL_FOLD_TO_BET,
    OpponentModel,
)

W = 2  # Beta(1, 1): duas pseudo-observações com média 0,5


def test_starts_at_weak_neutral_prior():
    m = OpponentModel()
    assert m.fold_to_bet == pytest.approx(NEUTRAL_FOLD_TO_BET)
    assert m.aggression == pytest.approx(NEUTRAL_AGGRESSION)
    assert m.samples == 0


def test_fold_to_bet_converges_toward_observed():
    m = OpponentModel()
    for _ in range(10):
        m.observe("fold", to_call=10)  # sempre desiste diante de aposta
    assert m.fold_to_bet == pytest.approx((10 + NEUTRAL_FOLD_TO_BET * W) / 12)
    assert m.fold_to_bet > NEUTRAL_FOLD_TO_BET
    assert m.samples == 10


def test_calling_station_drags_reads_below_prior():
    m = OpponentModel()
    for _ in range(10):
        m.observe("call", to_call=10)
    assert m.fold_to_bet == pytest.approx(NEUTRAL_FOLD_TO_BET * W / 12)
    assert m.fold_to_bet < NEUTRAL_FOLD_TO_BET
    assert m.aggression < NEUTRAL_AGGRESSION  # só pagou, nunca aumentou


def test_aggression_tracks_raises():
    m = OpponentModel()
    for _ in range(6):
        m.observe("raise", to_call=10)
    for _ in range(2):
        m.observe("call", to_call=10)
    assert m.aggression == pytest.approx((6 + NEUTRAL_AGGRESSION * W) / 10)
    assert m.aggression > NEUTRAL_AGGRESSION


def test_action_with_no_bet_to_call_is_not_fold_to_bet():
    m = OpponentModel()
    m.observe("check", to_call=0)  # check de graca nao conta como enfrentar aposta
    assert m.faced_bet == 0


def test_checks_do_not_contaminate_aggression_denominator():
    m = OpponentModel()
    for _ in range(50):
        m.observe("check", to_call=0)
    assert m.calls == 0
    assert m.raises == 0
    assert m.aggression == pytest.approx(NEUTRAL_AGGRESSION)


def test_read_returns_rounded_summary():
    m = OpponentModel()
    for _ in range(10):
        m.observe("fold", to_call=5)
    r = m.read()
    assert r.fold_to_bet == round((10 + NEUTRAL_FOLD_TO_BET * W) / 12, 2)
    assert r.samples == 10


def test_large_sample_overwhelms_the_prior():
    m = OpponentModel()
    for _ in range(200):
        m.observe("fold", to_call=10)
    assert m.fold_to_bet > 0.97  # com amostra grande, o prior vira detalhe


def test_each_observed_action_counts_as_one_sample():
    m = OpponentModel()
    m.observe("call", to_call=10)
    m.observe("raise", to_call=10)
    m.observe("check", to_call=0)
    assert m.samples == 3


def test_all_in_call_is_not_counted_as_a_raise():
    m = OpponentModel()
    m.observe("all_in", to_call=10, aggressive=False)
    assert m.calls == 1
    assert m.raises == 0


def test_tilt_delta_uses_the_frozen_pre_loss_baseline():
    m = OpponentModel()
    for _ in range(4):
        m.observe("call", to_call=10)
        m.observe("raise", to_call=10)
    m.note_hand_result(-20.0)
    for _ in range(3):
        m.observe("raise", to_call=10)

    assert m.tilt_delta == pytest.approx(0.5)
