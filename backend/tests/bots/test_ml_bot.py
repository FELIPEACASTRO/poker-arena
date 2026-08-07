import numpy as np
import onnx
import pytest
from onnx import TensorProto, helper, numpy_helper

from poker_arena.bots.ml_bot import EvaluationMLBot, MLBot
from poker_arena.bots.observation import Observation, PublicPlayer, observation_for
from poker_arena.engine.actions import ActionType
from poker_arena.engine.cards import Card, Rank, Suit
from poker_arena.engine.game import Hand
from poker_arena.engine.player import Player
from poker_arena.ml.encoder import FEATURE_SIZE, N_ACTIONS
from poker_arena.model_artifacts import ModelArtifactUnavailable
from tests.helpers.model_manifest import approve_expert


def _make_onnx(path, bias, inference_policy=None, *, state="approved"):
    """ONNX REAL minúsculo: logits = obs @ 0 + bias (constante). Fixture de teste."""
    w = numpy_helper.from_array(np.zeros((FEATURE_SIZE, N_ACTIONS), np.float32), "W")
    b = numpy_helper.from_array(np.asarray(bias, np.float32), "b")
    node = helper.make_node("Gemm", ["obs", "W", "b"], ["logits"])
    graph = helper.make_graph(
        [node],
        "expert",
        [helper.make_tensor_value_info("obs", TensorProto.FLOAT, [1, FEATURE_SIZE])],
        [helper.make_tensor_value_info("logits", TensorProto.FLOAT, [1, N_ACTIONS])],
        [w, b],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    onnx.checker.check_model(model)
    onnx.save(model, str(path))
    approve_expert(
        path,
        FEATURE_SIZE,
        N_ACTIONS,
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


def test_non_neutral_runtime_override_requires_manifest_approval(tmp_path):
    path = tmp_path / "expert.onnx"
    _make_onnx(path, [1.0, 1.0, -9.0, -9.0, -9.0])
    with pytest.raises(ValueError, match="approved in MANIFEST"):
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
