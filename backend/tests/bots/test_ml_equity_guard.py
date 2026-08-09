"""The rejected inference-time equity override remains documented but cannot deploy."""

import pytest

from poker_arena.bots.ml_bot import MLBot
from tests.helpers.expert_onnx import write_constant_expert_v2
from tests.helpers.model_manifest import approve_expert


def _fold_biased_onnx(path):
    write_constant_expert_v2(path, [9.0, *([0.0] * 9)])
    approve_expert(path)


def test_equity_guard_cannot_change_a_promoted_runtime_policy(tmp_path):
    path = tmp_path / "expert.onnx"
    _fold_biased_onnx(path)
    with pytest.raises(ValueError, match="rejected experiment"):
        MLBot(path, equity_guard=True)
