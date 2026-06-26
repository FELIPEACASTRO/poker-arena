from poker_arena.bots import HeuristicBot, RandomBot
from poker_arena.ml.evaluate import eval_bb100


def test_heuristic_profits_against_a_field_of_randoms():
    # heurístico (joga por equity) lucra contra um campo de randoms
    assert eval_bb100(HeuristicBot().act, "random", hands=400, seed=1) > 50


def test_heuristic_is_a_better_hero_than_random_vs_same_field():
    # contra os MESMOS vilões (random), o heurístico se sai melhor que o random.
    # bb/100 em poucas mãos tem variância ALTA, então tira-se a média de vários seeds
    # (em 1 seed só, o ruído pode inverter o resultado).
    seeds = [1, 2, 3, 4, 5]
    heur = sum(eval_bb100(HeuristicBot().act, villain="random", hands=200, seed=s) for s in seeds)
    rand = sum(eval_bb100(RandomBot(seed=0).act, villain="random", hands=200, seed=s) for s in seeds)
    assert heur > rand


def test_deterministic_for_same_seed():
    a = eval_bb100(HeuristicBot().act, "random", hands=200, seed=7)
    b = eval_bb100(HeuristicBot().act, "random", hands=200, seed=7)
    assert a == b
