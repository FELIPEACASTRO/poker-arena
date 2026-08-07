"""Guarda de equity do Expert (veto a fold dominado) — busca-lite de ESCOPO RESTRITO.

Só dispara em defesa BARATA (pot odds <= 30%) de pote PEQUENO (custo <= 10% do
stack) com folga de equity (>= preço + 10 pontos). A versão ampla foi REPROVADA
em benchmark pareado (all-in multiway: equity vs aleatório superestima) — o
escopo restrito ataca exatamente o vazamento medido (sangria de blinds).
"""

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper

from poker_arena.bots.ml_bot import MLBot, should_defend
from poker_arena.bots.observation import Observation, PublicPlayer
from poker_arena.engine.actions import ActionType
from poker_arena.engine.evaluator import card_from_str
from poker_arena.ml.encoder import FEATURE_SIZE, N_ACTIONS
from tests.helpers.model_manifest import approve_expert


# ---------- regra pura ----------
def test_defends_cheap_price_with_equity_edge():
    assert should_defend(equity=0.31, price=0.20, to_call=20, stack=1000) is True
    assert should_defend(equity=0.29, price=0.20, to_call=20, stack=1000) is False


def test_never_fires_on_expensive_bets():
    # preço acima de 30%: fora do escopo, mesmo com equity enorme
    assert should_defend(equity=0.90, price=0.40, to_call=20, stack=1000) is False


def test_never_fires_on_big_pots():
    # custo acima de 10% do stack: fora do escopo (evita variância de pote grande)
    assert should_defend(equity=0.60, price=0.20, to_call=200, stack=1000) is False


# ---------- integração (ONNX que SEMPRE quer desistir) ----------
def _fold_biased_onnx(path):
    w = numpy_helper.from_array(np.zeros((FEATURE_SIZE, N_ACTIONS), np.float32), "W")
    b = numpy_helper.from_array(np.asarray([9.0, 0.0, 0.0, 0.0, 0.0], np.float32), "b")
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
        inference_policy={
            "temperature": 0.0,
            "min_prob_ratio": 0.0,
            "sizing_jitter": 0.0,
        },
    )


def _obs(hole, to_call=10, pot=40, n_others=1):
    players = [PublicPlayer(0, "me", 1000, 0, 0, "active", True)] + [
        PublicPlayer(i, f"x{i}", 1000, to_call, to_call, "active", False)
        for i in range(1, n_others + 1)
    ]
    return Observation(
        seat=0,
        hole=tuple(card_from_str(c) for c in hole),
        board=(),
        pot=pot,
        to_call=to_call,
        current_bet=to_call,
        min_raise_to=to_call * 2,
        legal_actions=frozenset({ActionType.FOLD, ActionType.CALL, ActionType.RAISE}),
        players=tuple(players),
        num_active=n_others + 1,
    )


def test_guard_vetoes_dominated_fold_in_cheap_defense(tmp_path):
    # defesa barata (preço 20%) segurando AA (equity ~85%): rede fold-viciada é vetada
    path = tmp_path / "expert.onnx"
    _fold_biased_onnx(path)
    bot = MLBot(path, seed=3, sizing_jitter=0.0, equity_guard=True)
    action = bot.act(_obs(["Ah", "Ad"]))
    assert action.type in (ActionType.CALL, ActionType.CHECK)
    assert "veto matemático" in (bot.insight().label if bot.insight() else "")


def test_guard_respects_fold_with_trash_multiway(tmp_path):
    # 7-2o contra 4 oponentes (equity ~13% < limiar 30%): o fold fica de pé
    path = tmp_path / "expert.onnx"
    _fold_biased_onnx(path)
    bot = MLBot(path, seed=3, sizing_jitter=0.0, equity_guard=True)
    assert bot.act(_obs(["7h", "2c"], n_others=4)).type is ActionType.FOLD


def test_guard_out_of_scope_on_expensive_bet(tmp_path):
    # preço 40% (caro): fora do escopo — folda até AA (a política manda)
    path = tmp_path / "expert.onnx"
    _fold_biased_onnx(path)
    bot = MLBot(path, seed=3, sizing_jitter=0.0, equity_guard=True)
    assert bot.act(_obs(["Ah", "Ad"], to_call=10, pot=15)).type is ActionType.FOLD


def test_guard_is_off_by_default(tmp_path):
    # padrão = OFF: o experimento foi reprovado na medição (a política manda)
    path = tmp_path / "expert.onnx"
    _fold_biased_onnx(path)
    bot = MLBot(path, seed=3)
    assert bot.act(_obs(["Ah", "Ad"])).type is ActionType.FOLD
