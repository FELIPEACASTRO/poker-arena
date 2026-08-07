"""Copiloto de revisão de mãos — analisa um spot descrito pelo usuário (offline)."""

import logging

import pytest

import poker_arena.application.copilot as copilot_module
from poker_arena.application.copilot import InvalidSpotError, review_hand, review_spot

LEVELS = ["random", "heuristic", "montecarlo", "adaptive"]

# uma mão PHH real (Pluribus, Science 2019) — p2 (Gogo) vai ao showdown com 8sQh
_PHH = """variant = 'NT'
antes = [0, 0, 0, 0, 0, 0]
blinds_or_straddles = [50, 100, 0, 0, 0, 0]
min_bet = 100
starting_stacks = [10000, 10000, 10000, 10000, 10000, 10000]
actions = ['d dh p1 Ks7d', 'd dh p2 8sQh', 'd dh p3 2sKh', 'd dh p4 7c5d', 'd dh p5 Jh9d', 'd dh p6 TcJc', 'p3 f', 'p4 f', 'p5 f', 'p6 cbr 225', 'p1 f', 'p2 cc', 'd db 3dQc2c', 'p2 cc', 'p6 cbr 250', 'p2 cc', 'd db 9s', 'p2 cc', 'p6 cbr 1000', 'p2 cc', 'd db 5s', 'p2 cc', 'p6 cc', 'p2 sm 8sQh', 'p6 sm']
players = ['MrWhite', 'Gogo', 'Budd', 'Eddie', 'Bill', 'Pluribus']
"""


def test_strong_hand_facing_cheap_bet_recommends_continuing():
    # AA num board seco, preço barato -> jamais desistir
    v = review_spot(
        ["Ah", "As"],
        ["Kd", "7c", "2s"],
        pot=100,
        to_call=20,
        my_stack=1000,
        num_opponents=1,
        in_position=True,
        available_levels=LEVELS,
    )
    assert v.equity_pct >= 75
    assert v.recommendation in ("call", "raise", "all_in")  # nunca fold com nozes baratas
    fold = next(o for o in v.options if o.action == "fold")
    assert fold.verdict == "bad"  # desistir aqui e ruim
    assert v.ev_call > 0


def test_trash_facing_big_bet_recommends_fold():
    # 7-2 offsuit num board que nao ajuda, preço caro -> desistir
    v = review_spot(
        ["7h", "2c"],
        ["As", "Ks", "Qd"],
        pot=100,
        to_call=90,
        my_stack=1000,
        num_opponents=2,
        in_position=False,
        available_levels=LEVELS,
    )
    assert v.equity_pct < v.pot_odds_pct  # equity nao cobre o preço
    assert v.recommendation == "fold"
    call = next(o for o in v.options if o.action == "call")
    assert call.verdict == "bad"


def test_mdf_and_realization_and_council_present():
    v = review_spot(
        ["Ah", "Kh"],
        ["Qh", "Jh", "2c"],
        pot=100,
        to_call=50,
        my_stack=1000,
        num_opponents=1,
        in_position=True,
        available_levels=LEVELS,
    )
    # MDF = 1 - 50/100 -> ~50%
    assert v.mdf_pct is not None and 40 <= v.mdf_pct <= 60
    assert v.realization == "alta"  # em posição
    assert len(v.council) == len(LEVELS)  # uma recomendação por IA disponível
    assert v.hand_label and v.headline
    # com projeto de flush no board, deve listar o projeto
    assert any("flush" in d for d in v.draws)


def test_optional_council_failure_is_isolated_but_observable(monkeypatch, caplog):
    original = copilot_module._council_bot

    def one_broken_member(level, opponent_model):
        if level == "heuristic":
            raise RuntimeError("synthetic council failure")
        return original(level, opponent_model)

    monkeypatch.setattr(copilot_module, "_council_bot", one_broken_member)
    with caplog.at_level(logging.ERROR, logger=copilot_module.__name__):
        view = review_spot(
            ["Ah", "Kh"],
            ["Qh", "Jh", "2c"],
            pot=100,
            to_call=50,
            my_stack=1000,
            num_opponents=1,
            in_position=True,
            available_levels=LEVELS,
        )

    assert {entry.level for entry in view.council} == {
        "random",
        "montecarlo",
        "adaptive",
    }
    assert "falha ao calcular o conselho do nível heuristic" in caplog.text


def test_out_of_position_lowers_realization():
    v = review_spot(
        ["Ah", "Kh"],
        [],
        pot=30,
        to_call=0,
        my_stack=1000,
        num_opponents=3,
        in_position=False,
        available_levels=LEVELS,
    )
    assert v.realization == "baixa"
    assert v.mdf_pct is None  # sem aposta a pagar


def test_call_ev_is_zero_at_the_break_even_equity(monkeypatch):
    """At pot odds de 25%, a call de 25 em pote 75 tem EV exatamente zero."""
    monkeypatch.setattr(
        "poker_arena.application.copilot.estimate_equity",
        lambda *_args, **_kwargs: 0.25,
    )
    v = review_spot(
        ["Ah", "Kd"],
        [],
        pot=75,
        to_call=25,
        my_stack=1000,
        num_opponents=1,
        in_position=True,
        available_levels=[],
    )
    assert v.ev_call == 0.0


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


# ---------- revisão de mão inteira (PHH) ----------
def test_review_hand_walks_every_hero_decision():
    r = review_hand(_PHH, hero=1, available_levels=LEVELS)  # p2 = Gogo
    assert r.hero == "Gogo"
    assert r.total == len(r.decisions) >= 5  # pré-flop + várias ruas
    streets = {d.street for d in r.decisions}
    assert "pré-flop" in streets and "river" in streets
    # o board cresce ao longo das decisões e as cartas do herói aparecem
    river = next(d for d in r.decisions if d.street == "river")
    assert len(river.board) == 5 and set(river.hole) == {"8s", "Qh"}
    assert 0 <= r.matched <= r.total


def test_review_hand_rejects_unknown_player():
    with pytest.raises(InvalidSpotError):
        review_hand(_PHH, hero=99, available_levels=LEVELS)


def test_review_hand_rejects_garbage():
    with pytest.raises(InvalidSpotError):
        review_hand("isto não é PHH", hero=0, available_levels=LEVELS)


def test_review_hand_rejects_non_string_action_tokens():
    malformed = "starting_stacks=[100,100]\nactions=[5]"
    with pytest.raises(InvalidSpotError):
        review_hand(malformed, hero=1, available_levels=LEVELS)


@pytest.mark.parametrize(
    "token",
    [
        "",
        "d",
        "d xx p1 AsKd",
        "d dh p3 AsKd",
        "d dh p1 As",
        "d db AsKd",
        "pX cc",
        "p3 cc",
        "p1 cbr",
        "p1 cbr NaN",
        "p1 cc extra",
        "p1 unknown",
    ],
)
def test_review_hand_rejects_malformed_string_tokens(token):
    malformed = f"starting_stacks=[100,100]\nactions=[{token!r}]"
    with pytest.raises(InvalidSpotError, match="token PHH"):
        review_hand(malformed, hero=0, available_levels=LEVELS)


@pytest.mark.parametrize(
    "actions",
    [
        ["d dh p1 AsKd", "d dh p2 AsQh"],
        ["d dh p1 AsKd", "d dh p1 QsQh"],
        ["d dh p1 AsKd", "d db AsQhJh"],
        ["d db As"],
        ["p1 f", "p1 cc"],
        ["p1 cbr 101"],
        ["d dh p1 AsKd", "p1 sm AhKh"],
    ],
)
def test_review_hand_rejects_semantically_impossible_tokens(actions):
    malformed = f"starting_stacks=[100,100]\nactions={actions!r}"
    with pytest.raises(InvalidSpotError, match="token PHH"):
        review_hand(malformed, hero=0, available_levels=LEVELS)


@pytest.mark.parametrize(
    "metadata",
    [
        "starting_stacks=[true,100]",
        "starting_stacks=[100,100,100,100,100,100,100,100,100,100]",
        "starting_stacks=[100,100]\nblinds_or_straddles=[101,0]",
        "starting_stacks=[100,100]\nplayers=['ok', 5]",
    ],
)
def test_review_hand_rejects_invalid_table_metadata(metadata):
    with pytest.raises(InvalidSpotError):
        review_hand(f"{metadata}\nactions=[]", hero=0, available_levels=LEVELS)


# ---------- posição e nº de participantes (regra oficial) ----------
def test_position_flows_to_the_view():
    v = review_spot(["As", "Kh"], [], 30, 0, 1000, 4, True, LEVELS, position="BTN")
    assert v.position == "BTN"
    assert v.num_players == 5  # você + 4 oponentes
    assert v.realization == "alta"  # botão fecha a ação


def test_early_position_never_looser_than_button_preflop():
    # mesma mão marginal pré-flop enfrentando aposta: UTG (cedo) não pode ser MAIS
    # solto que o BTN (regra: aperta em posição cedo)
    order = {"fold": 0, "check": 1, "call": 2, "all_in": 3, "raise": 3}
    utg = review_spot(["Qd", "Jc"], [], 40, 20, 1000, 5, False, LEVELS, position="UTG")
    btn = review_spot(["Qd", "Jc"], [], 40, 20, 1000, 5, True, LEVELS, position="BTN")
    assert order[utg.recommendation] <= order[btn.recommendation]


def test_position_tax_can_turn_a_marginal_call_into_a_fold():
    from poker_arena.application.copilot import _recommend
    from poker_arena.bots.observation import Observation, PublicPlayer
    from poker_arena.engine.actions import ActionType
    from poker_arena.engine.evaluator import card_from_str

    me = PublicPlayer(0, "X", 1000, 0, 0, "active", False)
    obs = Observation(
        seat=0,
        hole=(card_from_str("Ah"), card_from_str("Kd")),
        board=(),
        pot=30,
        to_call=20,
        current_bet=20,
        min_raise_to=40,
        legal_actions=frozenset({ActionType.FOLD, ActionType.CALL, ActionType.RAISE}),
        players=(me,),
        num_active=2,
    )
    # equity 0.45 vs pot odds 0.40: paga sem tax; com tax posicional alto (0.10), folda
    assert _recommend(obs, 0.45, 40, obs.legal_actions, 0.0)[0] == ActionType.CALL
    assert _recommend(obs, 0.45, 40, obs.legal_actions, 0.10)[0] == ActionType.FOLD
