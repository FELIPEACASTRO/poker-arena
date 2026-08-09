"""Small real ONNX fixtures for the promoted Expert v2 contract."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper

from poker_arena.ml.action_space_v2 import N_ACTIONS_V2


def write_constant_expert_v2(path: Path, bias: Sequence[float]) -> Path:
    """Write a six-input v2 graph whose logits equal ``bias``."""

    values = np.asarray(bias, dtype=np.float32)
    if values.shape != (N_ACTIONS_V2,):
        raise ValueError("Expert v2 fixture bias must contain exactly ten logits")
    inputs = [
        helper.make_tensor_value_info("cards", TensorProto.FLOAT, [1, 208]),
        helper.make_tensor_value_info("global", TensorProto.FLOAT, [1, 24]),
        helper.make_tensor_value_info("seats", TensorProto.FLOAT, [1, 9, 12]),
        helper.make_tensor_value_info("history", TensorProto.FLOAT, [1, 15, 26]),
        helper.make_tensor_value_info("history_mask", TensorProto.FLOAT, [1, 15]),
        helper.make_tensor_value_info("legal_mask", TensorProto.FLOAT, [1, 10]),
    ]
    tensor = numpy_helper.from_array(values.reshape(1, -1), name="constant_logits")
    node = helper.make_node("Constant", [], ["logits"], value=tensor)
    graph = helper.make_graph(
        [node],
        "expert-v2-test-fixture",
        inputs,
        [helper.make_tensor_value_info("logits", TensorProto.FLOAT, [1, N_ACTIONS_V2])],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    onnx.checker.check_model(model)
    onnx.save(model, str(path))
    return path
