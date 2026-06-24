import numpy as np
import onnx
import pytest
from onnx import TensorProto, helper, numpy_helper

from poker_arena.application.bot_factory import (
    LEVELS,
    ExpertUnavailable,
    UnknownBotLevel,
    available_levels,
    create_bot,
)
from poker_arena.bots import HeuristicBot, MonteCarloBot, RandomBot
from poker_arena.bots.ml_bot import MLBot
from poker_arena.ml.encoder import FEATURE_SIZE, N_ACTIONS


def test_levels_registered():
    assert set(LEVELS) == {"random", "heuristic", "montecarlo", "expert"}


def test_create_each_heuristic_level():
    assert isinstance(create_bot("random"), RandomBot)
    assert isinstance(create_bot("heuristic"), HeuristicBot)
    assert isinstance(create_bot("montecarlo"), MonteCarloBot)


def test_unknown_level_raises():
    with pytest.raises(UnknownBotLevel):
        create_bot("supergto")


def test_expert_unavailable_without_model(monkeypatch, tmp_path):
    # sem modelo treinado -> Expert nao some das LEVELS, mas erra claro ao criar
    monkeypatch.setenv("POKER_EXPERT_MODEL", str(tmp_path / "nao_existe.onnx"))
    assert "expert" not in available_levels()
    with pytest.raises(ExpertUnavailable):
        create_bot("expert")


def test_expert_available_with_model(monkeypatch, tmp_path):
    path = tmp_path / "poker_expert.onnx"
    w = numpy_helper.from_array(np.zeros((FEATURE_SIZE, N_ACTIONS), np.float32), "W")
    b = numpy_helper.from_array(np.zeros(N_ACTIONS, np.float32), "b")
    node = helper.make_node("Gemm", ["obs", "W", "b"], ["logits"])
    graph = helper.make_graph(
        [node], "expert",
        [helper.make_tensor_value_info("obs", TensorProto.FLOAT, [1, FEATURE_SIZE])],
        [helper.make_tensor_value_info("logits", TensorProto.FLOAT, [1, N_ACTIONS])],
        [w, b],
    )
    onnx.save(helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)]), str(path))

    monkeypatch.setenv("POKER_EXPERT_MODEL", str(path))
    assert "expert" in available_levels()
    assert isinstance(create_bot("expert"), MLBot)
