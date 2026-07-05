"""OCR de números (pote + stacks) — o elo forte que substitui o template de dígitos.

O OCR (RapidOCR) roda em ~1-2s/imagem, então poucos casos: prova que lê o pote exato,
que separa pote (central) de stack (junto ao assento), e que o fallback (sem OCR) usa
o template. A acurácia em escala é medida no benchmark, não aqui.
"""

from __future__ import annotations

import numpy as np
import pytest

from poker_arena.vision import ocr
from poker_arena.vision.recognize import recognize_table
from poker_arena.vision.synth import CANONICAL, render_table

pytestmark = pytest.mark.skipif(not ocr.available(), reason="RapidOCR não instalado")


def test_le_o_pote_exato_por_ocr():
    img, truth = render_table(seed=7, style=CANONICAL, with_seats=True, n_board=5)
    st = recognize_table(img, ocr_numbers=True)
    assert st.pot == truth["pot"]
    assert st.pot_source == "ocr"


def test_le_stacks_dos_jogadores():
    img, _ = render_table(seed=3, style=CANONICAL, with_seats=True, n_board=3)
    st = recognize_table(img, ocr_numbers=True)
    assert st.stacks and len(st.stacks) >= 2  # leu fichas de vários assentos


def test_interpret_separa_pote_de_stack_por_geometria():
    # pote central + um número junto de um assento -> pote vira pot, o outro vira stack
    W, H = 900, 600
    nums = [(1500, W * 0.5, H * 0.32, 1.0),   # central -> pote
            (250, W * 0.12, H * 0.66, 1.0)]   # junto do assento 0 -> stack
    seats = [(W * 0.12, H * 0.64)]
    sn = ocr.interpret(nums, W, H, card_boxes=[], seat_centers=seats)
    assert sn.pot == 1500
    assert sn.stacks == {0: 250}


def test_ignora_numero_dentro_de_carta():
    # um "índice de carta" (número dentro de uma caixa de carta) não vira pote nem stack
    W, H = 900, 600
    nums = [(9, W * 0.5, H * 0.5, 1.0)]  # dentro da carta central
    card_boxes = [(int(W * 0.45), int(H * 0.45), int(W * 0.1), int(H * 0.14))]
    sn = ocr.interpret(nums, W, H, card_boxes=card_boxes, seat_centers=[])
    assert sn.pot is None and not sn.stacks


def test_fallback_template_quando_ocr_desligado():
    img, _ = render_table(seed=1, style=CANONICAL, n_board=3)
    st = recognize_table(img, ocr_numbers=False)
    assert st.pot_source == "template"
    assert st.stacks is None


def test_read_numbers_sem_engine_devolve_vazio(monkeypatch):
    monkeypatch.setattr(ocr, "_engine", lambda: None)
    assert ocr.read_numbers(np.zeros((100, 100, 3), np.uint8)) == []
    assert ocr.available() is False
