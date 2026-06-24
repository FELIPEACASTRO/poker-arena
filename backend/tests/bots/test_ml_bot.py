import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper

from poker_arena.bots.ml_bot import MLBot, _choose
from poker_arena.bots.observation import Observation, PublicPlayer, observation_for
from poker_arena.engine.actions import ActionType
from poker_arena.engine.cards import Card, Rank, Suit
from poker_arena.engine.game import Hand
from poker_arena.engine.player import Player
from poker_arena.ml.encoder import FEATURE_SIZE, N_ACTIONS


def _make_onnx(path, bias):
    """ONNX REAL minúsculo: logits = obs @ 0 + bias (constante). Fixture de teste."""
    w = numpy_helper.from_array(np.zeros((FEATURE_SIZE, N_ACTIONS), np.float32), "W")
    b = numpy_helper.from_array(np.asarray(bias, np.float32), "b")
    node = helper.make_node("Gemm", ["obs", "W", "b"], ["logits"])
    graph = helper.make_graph(
        [node], "expert",
        [helper.make_tensor_value_info("obs", TensorProto.FLOAT, [1, FEATURE_SIZE])],
        [helper.make_tensor_value_info("logits", TensorProto.FLOAT, [1, N_ACTIONS])],
        [w, b],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    onnx.checker.check_model(model)
    onnx.save(model, str(path))


def _obs(legal):
    players = (
        PublicPlayer(0, "me", 1000, 0, 0, "active", True),
        PublicPlayer(1, "x", 1000, 10, 10, "active", False),
    )
    return Observation(
        seat=0, hole=(Card(Rank.ACE, Suit.SPADES), Card(Rank.KING, Suit.SPADES)),
        board=(), pot=15, to_call=10, current_bet=10, min_raise_to=20,
        legal_actions=frozenset(legal), players=players, num_active=2,
    )


def _game_obs():
    players = [Player(f"P{i}", 1000) for i in range(6)]
    h = Hand(players, button=0, small_blind=10, big_blind=20, seed=1)
    h.start()
    return h, observation_for(h)


def test_choose_skips_illegal_and_picks_best_legal():
    obs = _obs({ActionType.FOLD, ActionType.CALL})  # raise/check/all_in ilegais
    logits = [0.1, 0.5, 9.0, 9.0, 9.0]  # maiores são ILEGAIS -> deve ignorar
    assert _choose(logits, obs).type == ActionType.CALL  # idx1 > idx0 entre os legais


def test_choose_respects_fold():
    obs = _obs({ActionType.FOLD, ActionType.CALL, ActionType.RAISE})
    assert _choose([9.0, 0.0, 0.0, 0.0, 0.0], obs).type == ActionType.FOLD


def test_mlbot_loads_real_onnx_and_plays_legally(tmp_path):
    path = tmp_path / "expert.onnx"
    _make_onnx(path, [10.0, 0.0, 0.0, 0.0, 0.0])  # logits mandam FOLD
    bot = MLBot(path)
    h, obs = _game_obs()
    action = bot.act(obs)
    assert action.type in h.legal_actions()  # sempre legal
    assert action.type == ActionType.FOLD  # seguiu os logits (fold é legal no preflop)
    assert "Expert" in bot.name
