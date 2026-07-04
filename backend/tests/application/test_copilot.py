"""Copiloto de revisão de mãos — analisa um spot descrito pelo usuário (offline)."""

import pytest

from poker_arena.application.copilot import InvalidSpotError, review_spot

LEVELS = ["random", "heuristic", "montecarlo", "adaptive"]


def test_strong_hand_facing_cheap_bet_recommends_continuing():
    # AA num board seco, preço barato -> jamais desistir
    v = review_spot(["Ah", "As"], ["Kd", "7c", "2s"], pot=100, to_call=20,
                    my_stack=1000, num_opponents=1, in_position=True, available_levels=LEVELS)
    assert v.equity_pct >= 75
    assert v.recommendation in ("call", "raise", "all_in")  # nunca fold com nozes baratas
    fold = next(o for o in v.options if o.action == "fold")
    assert fold.verdict == "bad"  # desistir aqui e ruim
    assert v.ev_call > 0


def test_trash_facing_big_bet_recommends_fold():
    # 7-2 offsuit num board que nao ajuda, preço caro -> desistir
    v = review_spot(["7h", "2c"], ["As", "Ks", "Qd"], pot=100, to_call=90,
                    my_stack=1000, num_opponents=2, in_position=False, available_levels=LEVELS)
    assert v.equity_pct < v.pot_odds_pct  # equity nao cobre o preço
    assert v.recommendation == "fold"
    call = next(o for o in v.options if o.action == "call")
    assert call.verdict == "bad"


def test_mdf_and_realization_and_council_present():
    v = review_spot(["Ah", "Kh"], ["Qh", "Jh", "2c"], pot=100, to_call=50,
                    my_stack=1000, num_opponents=1, in_position=True, available_levels=LEVELS)
    # MDF = 1 - 50/100 -> ~50%
    assert v.mdf_pct is not None and 40 <= v.mdf_pct <= 60
    assert v.realization == "alta"  # em posição
    assert len(v.council) == len(LEVELS)  # uma recomendação por IA disponível
    assert v.hand_label and v.headline
    # com projeto de flush no board, deve listar o projeto
    assert any("flush" in d for d in v.draws)


def test_out_of_position_lowers_realization():
    v = review_spot(["Ah", "Kh"], [], pot=30, to_call=0, my_stack=1000,
                    num_opponents=3, in_position=False, available_levels=LEVELS)
    assert v.realization == "baixa"
    assert v.mdf_pct is None  # sem aposta a pagar


@pytest.mark.parametrize(
    "hole,board,msg",
    [
        (["As", "As"], [], "repetida"),
        (["As"], [], "exatamente 2"),
        (["As", "Kh"], ["Qs", "Js"], "board deve ter"),
        (["Zz", "Kh"], [], "inválida"),
    ],
)
def test_invalid_spots_are_rejected(hole, board, msg):
    with pytest.raises(InvalidSpotError) as e:
        review_spot(hole, board, 100, 20, 1000, 1, True, LEVELS)
    assert msg in str(e.value)
