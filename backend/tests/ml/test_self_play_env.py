import random

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
