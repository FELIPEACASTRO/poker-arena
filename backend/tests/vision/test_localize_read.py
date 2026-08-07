"""F4 estágio LER (localize_read): crop+upscale+read com ausência graciosa do CNN.

Sem `card_reader.onnx` o reader cai no ZNCC (template sintético) e lê carta isolada limpa.
Quando o CNN existir (notebook 11), `read_card` o usa automático. Aqui cobrimos o fallback,
o upscale e a robustez a crops degenerados — o CNN em si é medido no harness de tela real.
"""

from __future__ import annotations

import numpy as np
import onnx
import pytest
from onnx import TensorProto, helper
from PIL import Image

from poker_arena.model_artifacts import ModelArtifactUnavailable
from poker_arena.vision import localize_read as lr
from poker_arena.vision.synth import CANONICAL, render_card
from tests.helpers.model_manifest import approve_card_reader


def _card_on_felt(rank: str, suit: str, w: int = 120):
    card = render_card(rank, suit, CANONICAL, w)
    cv = Image.new("RGB", (card.width + 40, card.height + 40), (30, 120, 50))
    cv.paste(card, (20, 20))
    return np.asarray(cv), (20, 20, card.width, card.height)


def _constant_reader(path):
    image = helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, 96, 64])
    rank = helper.make_tensor_value_info("rank", TensorProto.FLOAT, [1, 13])
    suit = helper.make_tensor_value_info("suit", TensorProto.FLOAT, [1, 4])
    rank_values = [0.0] * 12 + [9.0]  # A
    suit_values = [9.0, 0.0, 0.0, 0.0]  # s
    nodes = [
        helper.make_node(
            "Constant",
            [],
            ["rank"],
            value=helper.make_tensor("rank_v", TensorProto.FLOAT, [1, 13], rank_values),
        ),
        helper.make_node(
            "Constant",
            [],
            ["suit"],
            value=helper.make_tensor("suit_v", TensorProto.FLOAT, [1, 4], suit_values),
        ),
    ]
    model = helper.make_model(
        helper.make_graph(nodes, "reader", [image], [rank, suit]),
        opset_imports=[helper.make_opsetid("", 13)],
    )
    model.ir_version = 9
    onnx.save(model, str(path))
    approve_card_reader(path)


def test_card_reader_ausente_por_padrao(monkeypatch):
    monkeypatch.delenv("POKER_CARD_READER", raising=False)
    assert lr.card_reader_available() is False


def test_card_reader_existente_sem_manifesto_continua_no_fallback(monkeypatch, tmp_path):
    path = tmp_path / "card_reader.onnx"
    path.write_bytes(b"unapproved")
    monkeypatch.setenv("POKER_CARD_READER", str(path))
    assert lr.card_reader_available() is False
    rgb, box = _card_on_felt("A", "s")
    assert lr.read_card(rgb, box, upscale=1.0)[0] == "As"


def test_card_reader_aprovado_bate_contrato_e_e_usado(monkeypatch, tmp_path):
    path = tmp_path / "card_reader.onnx"
    _constant_reader(path)
    monkeypatch.setenv("POKER_CARD_READER", str(path))
    assert lr.card_reader_available() is True
    rgb, box = _card_on_felt("2", "d")  # CNN constante deve prevalecer sobre o template
    name, conf = lr.read_card(rgb, box, upscale=1.0)
    assert name == "As" and conf > 0.9


def test_le_carta_sintetica_via_zncc(monkeypatch):
    monkeypatch.delenv("POKER_CARD_READER", raising=False)
    rgb, box = _card_on_felt("A", "s")
    name, conf = lr.read_card(rgb, box, upscale=1.0)
    assert name == "As" and conf > 0.5


def test_upscale_nao_quebra_a_leitura(monkeypatch):
    monkeypatch.delenv("POKER_CARD_READER", raising=False)
    rgb, box = _card_on_felt("K", "h")
    name, _ = lr.read_card(rgb, box, upscale=3.0)
    assert name == "Kh"


def test_crop_degenerado_devolve_vazio():
    rgb = np.zeros((50, 50, 3), np.uint8)
    assert lr.read_card(rgb, (10, 10, 2, 2)) == ("", 0.0)  # box minúsculo


def test_read_cards_preserva_ordem(monkeypatch):
    monkeypatch.delenv("POKER_CARD_READER", raising=False)
    rgb, box = _card_on_felt("Q", "d")
    out = lr.read_cards(rgb, [box, box], upscale=1.0)
    assert len(out) == 2 and out[0][0] == "Qd"


@pytest.mark.parametrize("upscale", [-1.0, 0.0, 9.0, float("inf"), float("nan")])
def test_upscale_is_bounded(upscale):
    rgb, box = _card_on_felt("A", "s")
    with pytest.raises(ValueError, match="upscale"):
        lr.read_card(rgb, box, upscale=upscale)


def test_approved_cnn_runtime_failure_is_not_silently_hidden(monkeypatch):
    rgb, box = _card_on_felt("A", "s")
    monkeypatch.setattr(lr, "card_reader_available", lambda: True)

    def fail(_crop):
        raise ModelArtifactUnavailable("runtime_load_failed", "broken")

    monkeypatch.setattr(lr, "_cnn_read", fail)
    with pytest.raises(ModelArtifactUnavailable, match="runtime_load_failed"):
        lr.read_card(rgb, box, upscale=1.0)
