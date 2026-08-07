import logging

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
