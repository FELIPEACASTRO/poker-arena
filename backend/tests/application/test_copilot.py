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
    from poker_arena.bots.monte_carlo_bot import EquityEstimate

    monkeypatch.setattr(
        "poker_arena.application.copilot.estimate_equity_with_uncertainty",
        lambda *_args, **_kwargs: EquityEstimate(0.25, 100, "test-oracle", 0.0, 0.25, 0.25),
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
    malformed = (
        "variant='NT'\nantes=[0,0]\nblinds_or_straddles=[10,20]\nmin_bet=20\n"
        "starting_stacks=[100,100]\nactions=[5]"
    )
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
    malformed = (
        "variant='NT'\nantes=[0,0]\nblinds_or_straddles=[10,20]\nmin_bet=20\n"
        f"starting_stacks=[100,100]\nactions=[{token!r}]"
    )
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
    malformed = (
        "variant='NT'\nantes=[0,0]\nblinds_or_straddles=[10,20]\nmin_bet=20\n"
        f"starting_stacks=[100,100]\nactions={actions!r}"
    )
    with pytest.raises(InvalidSpotError, match="token PHH"):
        review_hand(malformed, hero=0, available_levels=LEVELS)


def test_review_hand_rejects_showdown_from_folded_player():
    malformed = """
variant='NT'
antes=[0,0]
blinds_or_straddles=[10,20]
min_bet=20
starting_stacks=[100,100]
actions=['d dh p1 AsAh','d dh p2 KsKh','p2 f','p2 sm KsKh']
"""
    with pytest.raises(InvalidSpotError, match="desistiu não pode mostrar"):
        review_hand(malformed, hero=1, available_levels=[])


def test_review_hand_rejects_duplicate_showdown_reveal():
    malformed = """
variant='NT'
antes=[0,0]
blinds_or_straddles=[10,20]
min_bet=20
starting_stacks=[20,20]
actions=['d dh p1 AsAh','d dh p2 KsKh','p2 cc','p1 sm AsAh','p1 sm AsAh']
"""
    with pytest.raises(InvalidSpotError, match="mostrou a mão duas vezes"):
        review_hand(malformed, hero=1, available_levels=[])


@pytest.mark.parametrize(
    ("phh", "message"),
    [
        (
            "variant='NT'\nantes=[0,0]\nblinds_or_straddles=[10,20]\n"
            "min_bet=20\nstarting_stacks=[true,100]\nactions=[]",
            "starting_stacks.*inteiros",
        ),
        (
            "variant='NT'\nantes=[0,0,0,0,0,0,0,0,0,0]\n"
            "blinds_or_straddles=[10,20,0,0,0,0,0,0,0,0]\nmin_bet=20\n"
            "starting_stacks=[100,100,100,100,100,100,100,100,100,100]\nactions=[]",
            "2 a 9 stacks",
        ),
        (
            "variant='NT'\nantes=[0,0]\nblinds_or_straddles=[10,20]\n"
            "min_bet=20\nstarting_stacks=[100,100]\nplayers=['ok', 5]\nactions=[]",
            "players.*mesmo tamanho",
        ),
    ],
)
def test_review_hand_rejects_invalid_table_metadata(phh, message):
    with pytest.raises(InvalidSpotError, match=message):
        review_hand(phh, hero=0, available_levels=LEVELS)


@pytest.mark.parametrize("blinds", ("[]", "[10,20]"))
def test_review_hand_requires_one_blind_or_straddle_entry_per_player(blinds):
    hand = f"""
variant='NT'
antes=[0,0,0]
blinds_or_straddles={blinds}
min_bet=20
starting_stacks=[100,100,100]
actions=['d dh p1 AsAd','d dh p2 KcKd','d dh p3 QsQd','p3 f','p1 f']
"""

    with pytest.raises(InvalidSpotError, match="blinds/straddles inválidos"):
        review_hand(hand, hero=0, available_levels=[])


def test_review_hand_caps_nominal_blind_to_short_stack_like_pokerkit():
    hand = """
variant='NT'
antes=[0,0,0]
blinds_or_straddles=[10,20,0]
min_bet=20
starting_stacks=[100,1,100]
actions=['d dh p1 QcJh','d dh p2 9c8d','d dh p3 AsKd','p3 cc','p1 cc','d db 2c3d4h','p1 cc','p3 cc','d db 5s','p1 cc','p3 cc','d db 6c','p1 cc','p3 cc']
"""

    result = review_hand(hand, hero=2, available_levels=[])

    assert result.total == 4
    assert result.decisions[0].to_call == 10


def test_review_hand_caps_nominal_ante_before_blind_like_pokerkit():
    hand = """
variant='NT'
antes=[0,50,0]
blinds_or_straddles=[10,20,0]
min_bet=20
starting_stacks=[100,21,100]
actions=['d dh p1 QcJh','d dh p2 9c8d','d dh p3 AsKd','p3 cc','p1 cc','d db 2c3d4h','p1 cc','p3 cc','d db 5s','p1 cc','p3 cc','d db 6c','p1 cc','p3 cc']
"""

    result = review_hand(hand, hero=2, available_levels=[])

    assert result.total == 4
    assert result.decisions[0].to_call == 10


def test_review_hand_rejects_phh_variant_outside_integer_nlhe_subset():
    with pytest.raises(InvalidSpotError, match="variant='NT'"):
        review_hand(
            "variant='FT'\nstarting_stacks=[100,100]\nactions=[]",
            hero=0,
            available_levels=[],
        )


def test_review_hand_rejects_action_out_of_order():
    malformed = """
variant='NT'
antes=[0,0]
blinds_or_straddles=[10,20]
min_bet=20
starting_stacks=[100,100]
actions=['d dh p1 KcKd','d dh p2 AsAd','p1 cc']
"""
    with pytest.raises(InvalidSpotError, match="fora da ordem; esperado p2"):
        review_hand(malformed, hero=1, available_levels=[])


def test_review_hand_preserves_real_raise_to_context():
    hand = """
variant='NT'
antes=[0,0,0]
blinds_or_straddles=[10,20,0]
min_bet=20
starting_stacks=[100,100,100]
actions=['d dh p1 KcKd','d dh p2 AsAd','d dh p3 QcJh','p3 cc','p1 cc','p2 cbr 40','p3 f','p1 f']
players=['SB','Hero BB','BTN']
"""
    result = review_hand(hand, hero=1, available_levels=[])

    assert result.total == 1
    assert result.decisions[0].to_call == 0
    assert result.decisions[0].recommendation == "raise"
    assert result.decisions[0].recommendation_label == "Aumentar p/ 40"
    assert result.decisions[0].recommendation_amount == 40
    assert result.decisions[0].your_amount == 40
    assert result.decisions[0].matched is True


def test_review_hand_raise_category_does_not_hide_wrong_sizing():
    hand = """
variant='NT'
antes=[0,0,0]
blinds_or_straddles=[10,20,0]
min_bet=20
starting_stacks=[100,100,100]
actions=['d dh p1 KcKd','d dh p2 AsAd','d dh p3 QcJh','p3 cc','p1 cc','p2 cbr 60','p3 f','p1 f']
players=['SB','Hero BB','BTN']
"""
    decision = review_hand(hand, hero=1, available_levels=[]).decisions[0]

    assert decision.recommendation == decision.your_action == "raise"
    assert decision.recommendation_amount == 40
    assert decision.your_amount == 60
    assert decision.matched is False


def test_review_hand_accepts_canonical_heads_up_reverse_blinds_and_action_order():
    hand = """
variant='NT'
antes=[0,0]
blinds_or_straddles=[10,20]
min_bet=20
starting_stacks=[100,100]
actions=['d dh p1 AsKd','d dh p2 QcJh','p2 cc','p1 cc','d db 2c3d4h','p1 cc','p2 cc','d db 5s','p1 cc','p2 cc','d db 6c','p1 cc','p2 cc']
players=['Hero BB','BTN/SB']
"""

    result = review_hand(hand, hero=0, available_levels=[])

    assert result.total == 4
    assert [decision.street for decision in result.decisions] == [
        "pré-flop",
        "flop",
        "turn",
        "river",
    ]


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
    assert _recommend(obs, 0.45, 0.40, obs.legal_actions, 0.0)[0] == ActionType.CALL
    assert _recommend(obs, 0.45, 0.40, obs.legal_actions, 0.10)[0] == ActionType.FOLD


def test_recommendation_uses_unrounded_pot_odds_at_the_boundary():
    from poker_arena.application.copilot import _recommend
    from poker_arena.bots.observation import Observation, PublicPlayer
    from poker_arena.engine.actions import ActionType
    from poker_arena.engine.evaluator import card_from_str

    me = PublicPlayer(0, "X", 1000, 0, 0, "active", False)
    obs = Observation(
        seat=0,
        hole=(card_from_str("Ah"), card_from_str("Kd")),
        board=(),
        pot=147,
        to_call=100,
        current_bet=100,
        min_raise_to=200,
        legal_actions=frozenset({ActionType.FOLD, ActionType.CALL}),
        players=(me,),
        num_active=2,
    )
    # 40,4% e 40,5% arredondariam ambos para 40%; a decisão deve manter a precisão.
    assert _recommend(obs, 0.404, 100 / 247, obs.legal_actions)[0] == ActionType.FOLD


def test_copilot_reports_exact_equity_provenance_and_effective_spr():
    view = review_spot(
        ["As", "Kd"],
        ["2h", "6c", "Tc", "3s", "9d"],
        pot=100,
        to_call=20,
        my_stack=1000,
        num_opponents=1,
        in_position=True,
        available_levels=[],
        effective_stack=350,
    )

    assert view.equity_method == "exact-river-heads-up"
    assert view.equity_trials == 990
    assert view.equity_standard_error_pct == 0.0
    assert view.equity_ci95_lower_pct == view.equity_ci95_upper_pct
    assert view.recommendation_stable is True
    assert view.spr == 3.5


def test_exact_stack_full_raise_is_recommended_as_all_in():
    view = review_spot(
        ["As", "Ad"],
        ["Kc", "Qd", "7h", "4s", "2c"],
        pot=100,
        to_call=20,
        my_stack=40,
        num_opponents=1,
        in_position=True,
        available_levels=[],
        big_blind=20,
    )

    assert view.equity_pct >= 80
    assert view.recommendation == "all_in"


def test_exact_stack_all_in_value_threshold_triggers_adaptive_resampling(monkeypatch):
    from poker_arena.application import copilot
    from poker_arena.bots.monte_carlo_bot import EquityEstimate

    budgets: list[int] = []

    def estimate(_hole, _board, _opponents, samples, _rng):
        budgets.append(samples)
        if samples == 5_000:
            return EquityEstimate(0.66, samples, "monte-carlo-uniform-range", 0.01, 0.65, 0.67)
        return EquityEstimate(0.70, samples, "monte-carlo-uniform-range", 0.005, 0.69, 0.71)

    monkeypatch.setattr(copilot, "estimate_equity_with_uncertainty", estimate)
    view = review_spot(
        ["As", "Ad"],
        [],
        pot=100,
        to_call=0,
        my_stack=20,
        num_opponents=1,
        in_position=False,
        available_levels=[],
        big_blind=20,
    )

    assert budgets == [5_000, 20_000]
    assert view.recommendation_stable is True


def test_copilot_rejects_position_impossible_for_table_size():
    with pytest.raises(InvalidSpotError, match="impossível para mesa original de 2"):
        review_spot(
            ["As", "Kd"],
            [],
            pot=30,
            to_call=10,
            my_stack=100,
            num_opponents=1,
            in_position=False,
            available_levels=[],
            position="UTG",
            table_size=2,
        )


def test_position_uses_original_table_size_not_only_active_opponents():
    view = review_spot(
        ["As", "Kd"],
        [],
        pot=30,
        to_call=10,
        my_stack=100,
        num_opponents=1,
        in_position=True,
        available_levels=[],
        position="BTN",
        table_size=3,
    )
    assert view.position == "BTN"


def test_explicit_postflop_position_is_not_overridden_by_preflop_label():
    """No heads-up, SB/BTN age por último pós-flop apesar do rótulo SB."""
    view = review_spot(
        ["As", "Kd"],
        ["2c", "7d", "Jh"],
        pot=30,
        to_call=10,
        my_stack=100,
        num_opponents=1,
        in_position=True,
        available_levels=[],
        position="SB",
        table_size=2,
    )

    assert view.realization == "alta"


def test_short_stack_call_is_canonical_all_in_with_effective_cost():
    view = review_spot(
        ["As", "Ad"],
        ["Kc", "Qd", "7h", "4s", "2c"],
        pot=100,
        to_call=100,
        my_stack=50,
        num_opponents=1,
        in_position=True,
        available_levels=[],
    )

    assert view.call_cost == 50
    assert view.pot_odds_pct == 33
    assert view.recommendation == "all_in"
    assert {option.action for option in view.options} == {"fold", "all_in"}
    assert "para pagar" in view.recommendation_label.lower()
    assert "call curto" in view.headline.lower()
    all_in_option = next(option for option in view.options if option.action == "all_in")
    assert "não é uma agressão" in all_in_option.reason


def test_fold_headline_does_not_claim_negative_ev_when_context_tax_decides():
    headline = copilot_module._headline(
        copilot_module.ActionType.FOLD,
        eq=45,
        po=40,
        to_call=20,
        ev=5.0,
    )

    assert "não é uma prova de call negativo" in headline
    assert "pagar é negativo" not in headline


def test_review_hand_rejects_reraise_after_short_all_in_did_not_reopen_action():
    hand = """
variant='NT'
antes=[0,0,0]
blinds_or_straddles=[10,20,0]
min_bet=20
starting_stacks=[200,80,200]
actions=['d dh p1 AsAd','d dh p2 KcKd','d dh p3 QsQd','p3 cbr 60','p1 cc','p2 cbr 80','p3 cbr 120']
"""
    with pytest.raises(InvalidSpotError, match="não foi reaberta"):
        review_hand(hand, hero=2, available_levels=[])


def test_manual_spot_preserves_button_feature_from_position_and_table_size(monkeypatch):
    from poker_arena.engine.actions import Action

    seen = []

    class SpyBot:
        def act(self, observation):
            seen.append(observation)
            return Action(next(iter(observation.legal_actions)))

        def insight(self):
            return None

    monkeypatch.setattr(copilot_module, "_council_bot", lambda *_args: SpyBot())
    review_spot(
        ["As", "Kd"],
        ["2c", "7d", "Jh"],
        pot=30,
        to_call=10,
        my_stack=100,
        num_opponents=1,
        in_position=True,
        available_levels=[],
        position="BB",
        table_size=3,
    )

    assert seen
    observation = seen[0]
    assert len(observation.players) == 3
    assert [player.seat for player in observation.players if player.is_button] == [1]
    assert observation.players[2].status == "folded"


def test_phh_position_after_button_fold_uses_last_remaining_postflop_actor(monkeypatch):
    original = copilot_module.review_spot
    in_position_values = []

    def capture(*args, **kwargs):
        in_position_values.append(kwargs["in_position"])
        return original(*args, **kwargs)

    monkeypatch.setattr(copilot_module, "review_spot", capture)
    hand = """
variant='NT'
antes=[0,0,0]
blinds_or_straddles=[10,20,0]
min_bet=20
starting_stacks=[100,100,100]
actions=['d dh p1 QcJh','d dh p2 AsKd','d dh p3 9c8d','p3 f','p1 cc','p2 cc','d db 2c3d4h','p1 cc','p2 cc','d db 5s','p1 cc','p2 cc','d db 6c','p1 cc','p2 cc']
"""

    review_hand(hand, hero=1, available_levels=[])

    assert in_position_values == [True, True, True, True]


def test_phh_position_ignores_all_in_seat_that_cannot_act(monkeypatch):
    original = copilot_module.review_spot
    in_position_values = []

    def capture(*args, **kwargs):
        in_position_values.append(kwargs["in_position"])
        return original(*args, **kwargs)

    monkeypatch.setattr(copilot_module, "review_spot", capture)
    hand = """
variant='NT'
antes=[0,0,0]
blinds_or_straddles=[10,20,0]
min_bet=20
starting_stacks=[100,100,15]
actions=['d dh p1 QcJh','d dh p2 AsKd','d dh p3 9c8d','p3 cc','p1 cc','p2 cc','d db 2c3d4h','p1 cc','p2 cc','d db 5s','p1 cc','p2 cc','d db 6c','p1 cc','p2 cc']
"""

    review_hand(hand, hero=1, available_levels=[])

    assert in_position_values == [True, True, True, True]


def test_phh_rejects_showdown_reveal_before_terminal_state():
    hand = """
variant='NT'
antes=[0,0]
blinds_or_straddles=[10,20]
min_bet=20
starting_stacks=[100,100]
actions=['d dh p1 ????','d dh p2 QcJh','p1 sm AsAd','p2 cc','p1 cc']
"""

    with pytest.raises(InvalidSpotError, match="showdown antes"):
        review_hand(hand, hero=0, available_levels=[])


def test_phh_normalizes_raise_all_in_as_all_in_not_raise():
    hand = """
variant='NT'
antes=[0,0]
blinds_or_straddles=[10,20]
min_bet=20
starting_stacks=[1000,50]
actions=['d dh p1 QcJh','d dh p2 AsAd','p2 cbr 50','p1 cc','d db 2c3d4h','d db 5s','d db 6c']
"""

    result = review_hand(hand, hero=1, available_levels=[])

    assert result.decisions[0].your_action == "all_in"
    assert result.decisions[0].matched is False


def test_phh_reviews_call_against_opponent_already_all_in():
    hand = """
variant='NT'
antes=[0,0]
blinds_or_straddles=[10,20]
min_bet=20
starting_stacks=[100,50]
actions=['d dh p1 AsAd','d dh p2 QcJh','p2 cbr 50','p1 cc','d db 2c3d4h','d db 5s','d db 6c']
"""

    result = review_hand(hand, hero=0, available_levels=[])

    assert result.decisions[0].your_action == "call"
    assert result.decisions[0].to_call == 30


def test_spot_forbids_aggression_when_every_opponent_is_already_all_in():
    view = review_spot(
        ["As", "Ad"],
        [],
        pot=100,
        to_call=0,
        my_stack=1_000,
        num_opponents=1,
        in_position=True,
        available_levels=[],
        effective_stack=0,
    )

    assert {option.action for option in view.options} == {"check"}
    assert view.recommendation == "check"


def test_phh_call_matches_when_only_opponent_is_already_all_in():
    hand = """
variant='NT'
antes=[0,0]
blinds_or_straddles=[10,20]
min_bet=20
starting_stacks=[20,100]
actions=['d dh p1 QcJh','d dh p2 AsAd','p2 cc','d db 2c3d4h','d db 5s','d db 6c']
"""

    result = review_hand(hand, hero=1, available_levels=[])

    assert result.decisions[0].to_call == 10
    assert result.decisions[0].your_action == "call"
    assert result.decisions[0].recommendation == "call"
    assert result.decisions[0].matched is True


def test_phh_rejects_raise_when_every_opponent_is_already_all_in():
    hand = """
variant='NT'
antes=[0,0]
blinds_or_straddles=[10,20]
min_bet=20
starting_stacks=[20,100]
actions=['d dh p1 QcJh','d dh p2 AsAd','p2 cbr 40','d db 2c3d4h','d db 5s','d db 6c']
"""

    with pytest.raises(InvalidSpotError, match="nenhum adversário pode contestar"):
        review_hand(hand, hero=1, available_levels=[])


def test_phh_normalizes_short_call_as_all_in_and_matches_canonical_recommendation():
    hand = """
variant='NT'
antes=[0,0,0]
blinds_or_straddles=[10,20,0]
min_bet=20
starting_stacks=[1000,1000,15]
actions=['d dh p1 QcJh','d dh p2 KcKd','d dh p3 AsAd','p3 cc','p1 cc','p2 cc','d db 2c3d4h','p1 cc','p2 cc','d db 5s','p1 cc','p2 cc','d db 6c','p1 cc','p2 cc']
"""

    result = review_hand(hand, hero=2, available_levels=[])

    assert result.decisions[0].your_action == "all_in"
    assert result.decisions[0].recommendation == "all_in"
    assert result.decisions[0].matched is True


def test_phh_short_stack_spot_excludes_opponent_uncalled_excess_from_pot():
    hand = """
variant='NT'
antes=[0,0]
blinds_or_straddles=[10,20]
min_bet=20
starting_stacks=[50,1000]
actions=['d dh p1 AsAd','d dh p2 QcJh','p2 cbr 100','p1 cc','d db 2c3d4h','d db 5s','d db 6c']
"""

    result = review_hand(hand, hero=0, available_levels=[])

    assert result.decisions[0].pot == 70
    assert result.decisions[0].to_call == 80


@pytest.mark.parametrize(
    "hand",
    [
        """
variant='NT'
antes=[0,0]
blinds_or_straddles=[10,20]
min_bet=20
starting_stacks=[100,100]
actions=['d dh p1 ????','d dh p2 AsKd','p2 cc']
""",
        """
variant='NT'
antes=[0,0]
blinds_or_straddles=[10,20]
min_bet=20
starting_stacks=[100,100]
actions=['d dh p1 ????','d dh p2 AsKd','p2 cc','p1 cc']
""",
    ],
)
def test_review_hand_rejects_non_terminal_history(hand):
    with pytest.raises(InvalidSpotError, match="truncado"):
        review_hand(hand, hero=1, available_levels=[])


def test_review_hand_rejects_hole_cards_dealt_after_actions_started():
    hand = """
variant='NT'
antes=[0,0]
blinds_or_straddles=[10,20]
min_bet=20
starting_stacks=[100,100]
actions=['d dh p1 ????','d dh p2 QcJh','p2 cc','d dh p1 AsKd','p1 cc']
"""

    with pytest.raises(InvalidSpotError, match="depois do inicio"):
        review_hand(hand, hero=1, available_levels=[])


def test_review_hand_requires_explicit_nlhe_variant():
    hand = """
blinds_or_straddles=[10,20]
starting_stacks=[100,100]
actions=['d dh p2 AsKd','p2 f']
"""

    with pytest.raises(InvalidSpotError, match="variant='NT'"):
        review_hand(hand, hero=1, available_levels=[])
