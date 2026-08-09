import math
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from poker_arena.bots.ml_bot import EvaluationMLBot, ExpertInferenceError, MLBot
from poker_arena.bots.observation import Observation, PublicPlayer, observation_for
from poker_arena.engine.actions import ActionType
from poker_arena.engine.cards import Card, Rank, Suit
from poker_arena.engine.game import Hand
from poker_arena.engine.player import Player
from poker_arena.ml.action_space_v2 import N_ACTIONS_V2
from poker_arena.model_artifacts import ModelArtifactUnavailable
from tests.helpers.expert_onnx import write_constant_expert_v2
from tests.helpers.model_manifest import approve_expert


def _make_onnx(path, bias, inference_policy=None, *, state="promoted"):
    """ONNX real mínimo do contrato v2 com logits constantes."""
    padded = [*bias, *([-20.0] * (N_ACTIONS_V2 - len(bias)))]
    write_constant_expert_v2(path, padded)
    approve_expert(
        path,
        state=state,
        inference_policy=inference_policy,
    )


def _obs(legal):
    players = (
        PublicPlayer(0, "me", 1000, 0, 0, "active", True),
        PublicPlayer(1, "x", 1000, 10, 10, "active", False),
    )
    return Observation(
        seat=0,
        hole=(Card(Rank.ACE, Suit.SPADES), Card(Rank.KING, Suit.SPADES)),
        board=(),
        pot=15,
        to_call=10,
        current_bet=10,
        min_raise_to=20,
        legal_actions=frozenset(legal),
        players=players,
        num_active=2,
    )


def _game_obs():
    players = [Player(f"P{i}", 1000) for i in range(6)]
    h = Hand(players, button=0, small_blind=10, big_blind=20, seed=1)
    h.start()
    return h, observation_for(h)


def test_masked_probs_skip_illegal_and_pick_best_legal(tmp_path):
    path = tmp_path / "expert.onnx"
    _make_onnx(
        path,
        [0.1, 0.5, 9.0, 9.0, 9.0],
        {"temperature": 0.0, "min_prob_ratio": 0.0, "sizing_jitter": 0.0},
    )  # maiores logits são ILEGAIS aqui
    bot = MLBot(path, temperature=0.0, sizing_jitter=0.0)  # modo argmax (determinístico)
    obs = _obs({ActionType.FOLD, ActionType.CALL})  # raise/check/all_in ilegais
    assert bot.act(obs).type == ActionType.CALL  # idx1 > idx0 entre os legais


def test_unsupported_modal_action_fails_closed_in_deploy_and_evaluation(tmp_path):
    policy = {
        "decision_rule": "modal",
        "temperature": 1.0,
        "min_prob_ratio": 0.0,
        "sizing_jitter": 0.0,
        "supported_action_indices": [0, 1, 2, 4, 5, 6, 7, 9],
    }
    logits = [0.0] * N_ACTIONS_V2
    logits[8] = 100.0
    logits[1] = 10.0
    obs = _obs({ActionType.FOLD, ActionType.CALL, ActionType.RAISE})

    deployed_path = tmp_path / "deployed.onnx"
    _make_onnx(deployed_path, logits, policy)
    deployed = MLBot(deployed_path, seed=0)
    assert deployed.act(obs).type is ActionType.FOLD
    assert deployed.insight() is not None
    assert "unsupported_action_modal" in deployed.insight().label

    candidate_path = tmp_path / "candidate.onnx"
    _make_onnx(candidate_path, logits, policy, state="candidate")
    evaluator = EvaluationMLBot(candidate_path, seed=0)
    with pytest.raises(ExpertInferenceError) as rejection:
        evaluator.policy_distribution(obs)
    assert rejection.value.code == "unsupported_action_modal"


def test_unsupported_nonmodal_actions_receive_exactly_zero_probability(tmp_path):
    path = tmp_path / "expert.onnx"
    logits = [0.0] * N_ACTIONS_V2
    logits[1] = 10.0
    logits[3] = 9.0
    _make_onnx(
        path,
        logits,
        {
            "decision_rule": "modal",
            "temperature": 1.0,
            "min_prob_ratio": 0.0,
            "sizing_jitter": 0.0,
            "supported_action_indices": [0, 1, 2, 4, 5, 6, 7, 9],
        },
    )
    probs = MLBot(path).policy_distribution(
        _obs({ActionType.FOLD, ActionType.CALL, ActionType.RAISE})
    )
    assert probs[3] == probs[8] == 0.0
    assert math.isclose(sum(probs), 1.0)


def test_argmax_mode_respects_fold(tmp_path):
    path = tmp_path / "expert.onnx"
    _make_onnx(
        path,
        [9.0, 0.0, 0.0, 0.0, 0.0],
        {"temperature": 0.0, "min_prob_ratio": 0.0, "sizing_jitter": 0.0},
    )
    # equity_guard=False: aqui testamos a POLÍTICA (a guarda tem testes próprios —
    # e ela de fato vetaria: AKs tem equity 67% > limiar 65% pra esse preço)
    bot = MLBot(path, temperature=0.0, sizing_jitter=0.0, equity_guard=False)
    obs = _obs({ActionType.FOLD, ActionType.CALL, ActionType.RAISE})
    assert bot.act(obs).type == ActionType.FOLD


def test_explicit_floor_can_make_confident_model_deterministic(tmp_path):
    # O corte não neutro só ocorre quando solicitado explicitamente.
    path = tmp_path / "expert.onnx"
    _make_onnx(
        path,
        [9.0, 0.0, 0.0, 0.0, 0.0],
        {"temperature": 1.0, "min_prob_ratio": 0.15, "sizing_jitter": 0.0},
    )
    bot = MLBot(path, min_prob_ratio=0.15, seed=1, equity_guard=False)
    obs = _obs({ActionType.FOLD, ActionType.CALL, ActionType.RAISE})
    assert all(bot.act(obs).type == ActionType.FOLD for _ in range(30))


def test_balanced_model_mixes_actions(tmp_path):
    # logits empatados entre fold e call: a estratégia mista deve variar a escolha
    path = tmp_path / "expert.onnx"
    _make_onnx(path, [1.0, 1.0, -9.0, -9.0, -9.0])
    bot = MLBot(path, seed=5)
    obs = _obs({ActionType.FOLD, ActionType.CALL})
    kinds = {bot.act(obs).type for _ in range(60)}
    assert kinds == {ActionType.FOLD, ActionType.CALL}  # imprevisível no spot parelho


def test_mixed_policy_distinguishes_modal_from_sampled_action(tmp_path):
    path = tmp_path / "expert.onnx"
    _make_onnx(path, [math.log(4.0), 0.0, -9.0, -9.0, -9.0])
    bot = MLBot(path, seed=0)

    action = bot.act(_obs({ActionType.FOLD, ActionType.CALL}))
    insight = bot.insight()

    assert action.type is ActionType.CALL
    assert insight is not None
    assert insight.modal_action == "fold"
    assert insight.executed_action == "check_call"
    assert insight.modal_probability is not None
    assert insight.executed_probability is not None
    assert insight.confidence == insight.modal_probability
    assert insight.modal_probability > insight.executed_probability
    assert insight.decision_rule == "sampled"
    assert insight.policy_entropy is not None and 0.0 < insight.policy_entropy < 1.0


def test_manifest_modal_rule_never_samples_a_lower_probability_action(tmp_path):
    path = tmp_path / "expert.onnx"
    _make_onnx(
        path,
        [math.log(4.0), 0.0, -9.0, -9.0, -9.0],
        {
            "decision_rule": "modal",
            "temperature": 1.0,
            "min_prob_ratio": 0.0,
            "sizing_jitter": 0.0,
        },
    )
    bot = MLBot(path, seed=0)

    assert bot.act(_obs({ActionType.FOLD, ActionType.CALL})).type is ActionType.FOLD
    insight = bot.insight()
    assert insight is not None
    assert insight.executed_action == insight.modal_action == "fold"
    assert insight.decision_rule == "modal"


@pytest.mark.parametrize(
    "raw_output",
    [
        np.asarray([[np.nan, *([0.0] * 9)]], dtype=np.float32),
        np.asarray([[np.inf, *([0.0] * 9)]], dtype=np.float32),
        np.asarray([[0.0, 0.0]], dtype=np.float32),
    ],
)
def test_invalid_runtime_output_uses_non_aggressive_fail_safe(tmp_path, raw_output):
    path = tmp_path / "expert.onnx"
    _make_onnx(path, [0.0] * N_ACTIONS_V2)
    bot = MLBot(path, seed=0)
    bot._session = SimpleNamespace(run=lambda *_args, **_kwargs: [raw_output])

    action = bot.act(_obs({ActionType.FOLD, ActionType.CALL, ActionType.RAISE}))
    insight = bot.insight()

    assert action.type is ActionType.FOLD
    assert insight is not None
    assert insight.confidence == 0.0
    assert insight.probs is None
    assert "fallback legal determinístico" in insight.label


def test_inconsistent_raise_only_observation_raises_closed_fallback_error(tmp_path):
    path = tmp_path / "expert.onnx"
    _make_onnx(path, [0.0] * N_ACTIONS_V2)
    original = _obs({ActionType.RAISE})
    obs = replace(
        original,
        min_raise_to=original.players[0].current_bet + original.players[0].stack,
    )

    with pytest.raises(ExpertInferenceError) as rejection:
        MLBot(path).act(obs)
    assert rejection.value.code == "fallback_legal_state_inconsistent"


def test_evaluation_candidate_aborts_instead_of_hiding_invalid_output(tmp_path):
    path = tmp_path / "candidate.onnx"
    _make_onnx(path, [0.0] * N_ACTIONS_V2, state="candidate")
    evaluator = EvaluationMLBot(path, seed=0)
    evaluator._session = SimpleNamespace(
        run=lambda *_args, **_kwargs: [np.asarray([[np.nan, *([0.0] * 9)]], dtype=np.float32)]
    )

    with pytest.raises(ExpertInferenceError) as rejection:
        evaluator.act(_obs({ActionType.FOLD, ActionType.CALL}))
    assert rejection.value.code == "output_non_finite"


def test_non_neutral_runtime_override_requires_manifest_approval(tmp_path):
    path = tmp_path / "expert.onnx"
    _make_onnx(path, [1.0, 1.0, -9.0, -9.0, -9.0])
    with pytest.raises(ValueError, match="must match the approved manifest"):
        MLBot(path, temperature=0.75)


def test_mlbot_loads_real_onnx_and_plays_legally(tmp_path):
    path = tmp_path / "expert.onnx"
    _make_onnx(
        path,
        [10.0, 0.0, 0.0, 0.0, 0.0],
        {"temperature": 0.0, "min_prob_ratio": 0.0, "sizing_jitter": 0.0},
    )  # logits mandam FOLD
    bot = MLBot(path, temperature=0.0)
    h, obs = _game_obs()
    action = bot.act(obs)
    assert action.type in h.legal_actions()  # sempre legal
    assert action.type == ActionType.FOLD  # seguiu os logits (fold é legal no preflop)
    assert "Expert" in bot.name


def test_candidate_has_explicit_evaluation_lane_but_deploy_bot_rejects_it(tmp_path):
    path = tmp_path / "candidate.onnx"
    _make_onnx(
        path,
        [10.0, 0.0, 0.0, 0.0, 0.0],
        {"temperature": 0.0, "min_prob_ratio": 0.0, "sizing_jitter": 0.0},
        state="candidate",
    )

    with pytest.raises(ModelArtifactUnavailable) as deployment_rejection:
        MLBot(path)
    assert deployment_rejection.value.code == "state_not_approved"

    evaluator = EvaluationMLBot(path, temperature=0.0, seed=1)
    h, obs = _game_obs()
    action = evaluator.act(obs)
    assert action.type in h.legal_actions()
    assert "Evaluation Candidate" in evaluator.name
