import pytest

from poker_arena.application.bot_factory import LEVELS, UnknownBotLevel, create_bot
from poker_arena.bots import HeuristicBot, MonteCarloBot, RandomBot


def test_levels_registered():
    assert set(LEVELS) == {"random", "heuristic", "montecarlo"}


def test_create_each_level():
    assert isinstance(create_bot("random"), RandomBot)
    assert isinstance(create_bot("heuristic"), HeuristicBot)
    assert isinstance(create_bot("montecarlo"), MonteCarloBot)


def test_unknown_level_raises():
    with pytest.raises(UnknownBotLevel):
        create_bot("supergto")
