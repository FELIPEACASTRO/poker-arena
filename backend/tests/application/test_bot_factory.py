import pytest

from poker_arena.application.bot_factory import (
    LEVELS,
    ExpertUnavailable,
    UnknownBotLevel,
    available_levels,
    create_bot,
    expert_model_available,
)
from poker_arena.bots import HeuristicBot, MonteCarloBot, RandomBot
from poker_arena.bots.ml_bot import MLBot
from tests.helpers.expert_onnx import write_constant_expert_v2
from tests.helpers.model_manifest import approve_expert


def _approve_expert(path, *, state="promoted"):
    approve_expert(path, state=state)


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


def test_expert_file_alone_is_not_available(monkeypatch, tmp_path):
    path = tmp_path / "poker_expert.onnx"
    path.write_bytes(b"not-governed")
    monkeypatch.setenv("POKER_EXPERT_MODEL", str(path))
    assert not expert_model_available()
    assert "expert" not in available_levels()
    with pytest.raises(ExpertUnavailable, match="gate"):
        create_bot("expert")


def test_expert_available_with_model(monkeypatch, tmp_path):
    path = tmp_path / "poker_expert.onnx"
    write_constant_expert_v2(path, [0.0] * 10)
    _approve_expert(path)

    monkeypatch.setenv("POKER_EXPERT_MODEL", str(path))
    assert expert_model_available()
    assert "expert" in available_levels()
    assert isinstance(create_bot("expert"), MLBot)


def test_candidate_never_becomes_factory_runtime_level(monkeypatch, tmp_path):
    path = tmp_path / "poker_expert.onnx"
    path.write_bytes(b"candidate-is-not-deployment")
    _approve_expert(path, state="candidate")
    monkeypatch.setenv("POKER_EXPERT_MODEL", str(path))

    assert not expert_model_available()
    assert "expert" not in available_levels()
    with pytest.raises(ExpertUnavailable):
        create_bot("expert")
