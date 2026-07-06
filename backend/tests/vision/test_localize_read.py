"""F4 estágio LER (localize_read): crop+upscale+read com ausência graciosa do CNN.

Sem `card_reader.onnx` o reader cai no ZNCC (template sintético) e lê carta isolada limpa.
Quando o CNN existir (notebook 11), `read_card` o usa automático. Aqui cobrimos o fallback,
o upscale e a robustez a crops degenerados — o CNN em si é medido no harness de tela real.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from poker_arena.vision import localize_read as lr
from poker_arena.vision.synth import CANONICAL, render_card


def _card_on_felt(rank: str, suit: str, w: int = 120):
    card = render_card(rank, suit, CANONICAL, w)
    cv = Image.new("RGB", (card.width + 40, card.height + 40), (30, 120, 50))
    cv.paste(card, (20, 20))
    return np.asarray(cv), (20, 20, card.width, card.height)


def test_card_reader_ausente_por_padrao(monkeypatch):
    monkeypatch.delenv("POKER_CARD_READER", raising=False)
    assert lr.card_reader_available() is False


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
