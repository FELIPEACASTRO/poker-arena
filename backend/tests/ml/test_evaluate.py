from types import SimpleNamespace

import pytest

from poker_arena.bots import HeuristicBot, RandomBot
from poker_arena.ml.evaluate import _play_out, _villain_seeds, eval_bb100


def test_heuristic_profits_against_a_field_of_randoms():
    # heurístico (joga por equity) lucra contra um campo de randoms
    assert eval_bb100(HeuristicBot().act, "random", hands=400, seed=1) > 50


def test_heuristic_is_a_better_hero_than_random_vs_same_field():
    # contra os MESMOS vilões (random), o heurístico se sai melhor que o random.
    # bb/100 em poucas mãos tem variância ALTA, então tira-se a média de vários seeds
    # (em 1 seed só, o ruído pode inverter o resultado).
    seeds = list(range(1, 11))
    heur = sum(eval_bb100(HeuristicBot().act, villain="random", hands=200, seed=s) for s in seeds)
    rand = sum(
        eval_bb100(RandomBot(seed=0).act, villain="random", hands=200, seed=s) for s in seeds
    )
    assert heur > rand


def test_deterministic_for_same_seed():
    a = eval_bb100(HeuristicBot().act, "random", hands=200, seed=7)
    b = eval_bb100(HeuristicBot().act, "random", hands=200, seed=7)
    assert a == b


def test_villain_seed_stream_is_reproducible_but_panel_specific():
    assert _villain_seeds(7, 5) == _villain_seeds(7, 5)
    assert _villain_seeds(7, 5) != _villain_seeds(8, 5)
    assert len(set(_villain_seeds(7, 5))) == 5


class _NeverResolvingHand:
    players = [SimpleNamespace(status="active"), SimpleNamespace(status="active")]
    board = []

    def round_complete(self):
        return True

    def advance_street(self):
        return None


def test_play_out_fails_closed_when_transition_guard_is_exhausted():
    with pytest.raises(RuntimeError, match="did not resolve"):
        _play_out(_NeverResolvingHand(), lambda _obs: None, [])


@pytest.mark.parametrize(
    "kwargs",
    [
        {"hands": 0},
        {"n": 1},
        {"stack": 0},
        {"sb": 0},
        {"sb": 20, "bb": 20},
        {"stack": 10, "bb": 20},
    ],
)
def test_eval_rejects_invalid_configuration(kwargs):
    with pytest.raises(ValueError):
        eval_bb100(HeuristicBot().act, "random", **kwargs)


def test_eval_rejects_unknown_villain():
    with pytest.raises(ValueError, match="unknown villain"):
        eval_bb100(HeuristicBot().act, "not-a-bot", hands=1)
