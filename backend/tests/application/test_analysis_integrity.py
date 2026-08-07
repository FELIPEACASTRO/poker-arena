import logging

import pytest

from poker_arena.application import analysis
from poker_arena.bots.opponent_model import OpponentModel
from poker_arena.engine.evaluator import card_from_str
from poker_arena.engine.game import Hand
from poker_arena.engine.player import Player


def _c(value: str):
    return card_from_str(value)


def _disable_council(monkeypatch) -> None:
    def unavailable(*_args, **_kwargs):
        raise RuntimeError("council disabled for this focused equity test")

    monkeypatch.setattr(analysis, "_council_bot", unavailable)


def test_live_analysis_never_uses_opponent_hole_cards(monkeypatch):
    _disable_council(monkeypatch)
    hand = Hand(
        [Player("Hero", 1000), Player("Villain", 1000)],
        button=0,
        small_blind=10,
        big_blind=20,
        seed=1,
    )
    hand.start()
    hand.to_act = 0
    hand.board = [_c("2h"), _c("3d"), _c("4s"), _c("9c"), _c("Jd")]
    hand.players[0].hole = [_c("Ah"), _c("Ad")]

    hand.players[1].hole = [_c("Kh"), _c("Kd")]
    first = analysis.analyze(hand, 0, OpponentModel(), [], samples=80).equity

    # O estado publico e identico; so cartas invisiveis do vilao mudam.
    hand.players[1].hole = [_c("5h"), _c("6h")]
    second = analysis.analyze(hand, 0, OpponentModel(), [], samples=80).equity

    assert first == second


def test_repeated_live_analysis_is_deterministic_and_does_not_consume_bot_rng():
    hand = Hand(
        [Player("Hero", 1000), Player("Villain", 1000)],
        button=0,
        small_blind=10,
        big_blind=20,
        seed=5,
    )
    hand.start()
    seat = hand.to_act
    model = OpponentModel()

    results = [analysis.analyze(hand, seat, model, [], samples=30) for _ in range(3)]
    councils = [
        [(c.level, c.action, c.amount, c.confidence) for c in result.council] for result in results
    ]

    assert councils[0] == councils[1] == councils[2]


def test_council_failure_is_isolated_but_observable(monkeypatch, caplog):
    _disable_council(monkeypatch)
    hand = Hand(
        [Player("Hero", 1000), Player("Villain", 1000)],
        button=0,
        small_blind=10,
        big_blind=20,
        seed=9,
    )
    hand.start()

    with caplog.at_level(logging.ERROR, logger=analysis.__name__):
        result = analysis.analyze(hand, hand.to_act, OpponentModel(), [], samples=20)

    assert result.council == []
    assert "falha ao calcular o conselho ao vivo do nível adaptive" in caplog.text


def test_live_analysis_does_not_label_a_baseline_best_without_expert():
    hand = Hand(
        [Player("Hero", 1000), Player("Villain", 1000)],
        button=0,
        small_blind=10,
        big_blind=20,
        seed=12,
    )
    hand.start()

    result = analysis.analyze(hand, hand.to_act, OpponentModel(), [], samples=20)

    assert result.council
    assert all(entry.level != "expert" for entry in result.council)
    assert result.best_action is None
    assert result.best_amount is None
    assert result.confidence is None


@pytest.mark.parametrize(
    ("hole", "board", "expected_outs", "expected_draws"),
    [
        (("As", "2d"), ("3c", "4h", "Kd"), 4, ["projeto/melhoria de sequência"]),
        (("9s", "8d"), ("7c", "6h", "Kd"), 8, ["projeto/melhoria de sequência"]),
        (("2c", "3d"), ("Ah", "Kh", "Qh", "Jh"), 0, []),
        (("8s", "9d"), ("5c", "6h", "7d"), 4, ["projeto/melhoria de sequência"]),
    ],
)
def test_structural_outs_require_hero_contribution_and_include_wheel(
    hole, board, expected_outs, expected_draws
):
    assert analysis._outs_and_draws(
        tuple(_c(card) for card in hole), tuple(_c(card) for card in board)
    ) == (expected_outs, expected_draws)


def test_live_analysis_uses_only_hero_eligible_pot_for_short_all_in(monkeypatch):
    _disable_council(monkeypatch)
    monkeypatch.setattr(analysis, "_win_probs", lambda *_args, **_kwargs: {0: 0.8, 1: 0.2})
    players = [Player("Hero", 30), Player("Villain", 900)]
    hand = Hand(players, button=1, small_blind=10, big_blind=20, seed=1)
    hand._started = True
    hand.to_act = 0
    hand.current_bet = 100
    hand.pot = 120
    players[0].current_bet = players[0].total_committed = 20
    players[1].current_bet = players[1].total_committed = 100
    players[0].hole = [_c("As"), _c("Ad")]

    result = analysis.analyze(hand, 0, OpponentModel(), [], samples=100)

    assert result.call_cost == 30
    assert result.pot_odds == 0.3
    assert result.ev_call == 50.0
    assert result.mdf is None


def test_uniform_range_villains_have_exchangeable_displayed_equity():
    probabilities = analysis._win_probs(
        0,
        (_c("As"), _c("Kd")),
        [0, 1, 2, 3],
        (_c("2h"), _c("6c"), _c("Tc")),
        500,
    )

    assert probabilities[1] == probabilities[2] == probabilities[3]
    assert sum(probabilities.values()) == pytest.approx(1.0)


def test_texture_is_factual_and_handles_wheel_and_paired_boards():
    wheel = analysis._texture((_c("As"), _c("2d"), _c("3c")))
    paired = analysis._texture((_c("Kh"), _c("Kd"), _c("2c")))

    assert wheel is not None and "conectado" in wheel and "tranquilo" not in wheel
    assert paired is not None and "pareado" in paired and "tranquilo" not in paired
