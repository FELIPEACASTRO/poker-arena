import random

import pytest

from poker_arena.ml.encoder import FEATURE_SIZE, N_ACTIONS
from poker_arena.ml.self_play_env import SelfPlayEnv


def _pick(mask, rng):
    return rng.choice([i for i, ok in enumerate(mask) if ok])


def test_reset_returns_valid_obs_and_mask():
    obs, mask = SelfPlayEnv(seed=1).reset()
    assert len(obs) == FEATURE_SIZE
    assert len(mask) == N_ACTIONS
    assert any(mask)  # sempre há ao menos uma ação legal


def test_episode_terminates_and_conserves_chips():
    rng = random.Random(2)
    env = SelfPlayEnv(seed=3)
    _, mask = env.reset()
    done, steps, reward = False, 0, 0.0
    while not done and steps < 300:
        _, mask, reward, done = env.step(_pick(mask, rng))
        steps += 1
    assert done
    # conservação: a soma das variações de fichas de todos é zero
    assert sum(p.stack - env.stack for p in env._players) == 0


def test_many_episodes_run_without_crashing():
    rng = random.Random(4)
    env = SelfPlayEnv(seed=5)
    for _ in range(40):
        _, mask = env.reset()
        done = False
        while not done:
            _, mask, _, done = env.step(_pick(mask, rng))


def test_heads_up_also_works():
    rng = random.Random(6)
    env = SelfPlayEnv(n_players=2, seed=7)
    _, mask = env.reset()
    done = False
    while not done:
        _, mask, _, done = env.step(_pick(mask, rng))
    assert sum(p.stack - env.stack for p in env._players) == 0


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"n_players": 1}, "n_players"),
        ({"starting_stack": 0}, "starting_stack"),
        ({"small_blind": 0}, "blinds"),
        ({"small_blind": 20, "big_blind": 20}, "blinds"),
        ({"starting_stack": 10, "big_blind": 20}, "big_blind"),
    ],
)
def test_constructor_rejects_invalid_game_configuration(kwargs, message):
    with pytest.raises(ValueError, match=message):
        SelfPlayEnv(**kwargs)


def test_step_rejects_negative_and_illegal_indices_without_fallback():
    env = SelfPlayEnv(seed=11)
    _, mask = env.reset()
    with pytest.raises(ValueError, match="action_index"):
        env.step(-1)

    illegal = next((index for index, allowed in enumerate(mask) if not allowed), None)
    if illegal is not None:
        with pytest.raises(ValueError, match="illegal"):
            env.step(illegal)


def test_opponent_policy_index_is_validated():
    env = SelfPlayEnv(opponent=lambda _features, _mask: -1, seed=12)
    with pytest.raises(ValueError, match="action_index"):
        env.reset()


def test_reset_seed_restarts_the_exact_environment_stream():
    env = SelfPlayEnv(seed=99)
    first = env.reset(seed=123)
    second = env.reset(seed=123)
    assert second == first


def test_reset_rejects_non_integer_seed():
    with pytest.raises(TypeError, match="seed"):
        SelfPlayEnv().reset(seed=True)
