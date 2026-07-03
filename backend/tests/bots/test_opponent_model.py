"""OpponentModel com PRIORS POPULACIONAIS (250k mãos reais; notebook 07).

Semântica bayesiana: sem dados, a leitura começa no HUMANO TÍPICO medido
(fold-to-bet 0.70, agressão 0.46, peso 8 pseudo-amostras) e converge para o
oponente REAL conforme observa. Fórmula: (observado + prior×8) / (n + 8).
"""

import pytest

from poker_arena.bots.opponent_model import (
    POP_AGGRESSION,
    POP_FOLD_TO_BET,
    OpponentModel,
)

W = 8  # _PRIOR_WEIGHT


def test_starts_at_population_prior_not_neutral():
    m = OpponentModel()
    assert m.fold_to_bet == pytest.approx(POP_FOLD_TO_BET)  # 0.70, humano típico
    assert m.aggression == pytest.approx(POP_AGGRESSION)  # 0.46
    assert m.samples == 0


def test_fold_to_bet_converges_toward_observed():
    m = OpponentModel()
    for _ in range(10):
        m.observe("fold", to_call=10)  # sempre desiste diante de aposta
    # (10 + 0.70*8) / (10 + 8) = 0.8667 — subiu MUITO acima do prior, rumo a 1.0
    assert m.fold_to_bet == pytest.approx((10 + POP_FOLD_TO_BET * W) / 18)
    assert m.fold_to_bet > POP_FOLD_TO_BET
    assert m.samples == 10


def test_calling_station_drags_reads_below_prior():
    m = OpponentModel()
    for _ in range(10):
        m.observe("call", to_call=10)
    # nunca desistiu: (0 + 5.6)/18 = 0.31 — bem abaixo do prior, rumo a 0
    assert m.fold_to_bet == pytest.approx(POP_FOLD_TO_BET * W / 18)
    assert m.fold_to_bet < POP_FOLD_TO_BET
    assert m.aggression < POP_AGGRESSION  # só pagou, nunca aumentou


def test_aggression_tracks_raises():
    m = OpponentModel()
    for _ in range(6):
        m.observe("raise", to_call=10)
    for _ in range(2):
        m.observe("call", to_call=10)
    # (6 + 0.46*8) / (8 + 8) = 0.605
    assert m.aggression == pytest.approx((6 + POP_AGGRESSION * W) / 16)
    assert m.aggression > POP_AGGRESSION


def test_action_with_no_bet_to_call_is_not_fold_to_bet():
    m = OpponentModel()
    m.observe("check", to_call=0)  # check de graca nao conta como enfrentar aposta
    assert m.faced_bet == 0


def test_read_returns_rounded_summary():
    m = OpponentModel()
    for _ in range(10):
        m.observe("fold", to_call=5)
    r = m.read()
    assert r.fold_to_bet == round((10 + POP_FOLD_TO_BET * W) / 18, 2)  # 0.87
    assert r.samples == 10


def test_large_sample_overwhelms_the_prior():
    m = OpponentModel()
    for _ in range(200):
        m.observe("fold", to_call=10)
    assert m.fold_to_bet > 0.97  # com amostra grande, o prior vira detalhe