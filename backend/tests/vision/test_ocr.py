"""OCR de números (pote + stacks) — o elo forte que substitui o template de dígitos.

O OCR (RapidOCR) roda em ~1-2s/imagem, então poucos casos: prova que lê o pote exato,
que separa pote (central) de stack (junto ao assento), e que o fallback (sem OCR) usa
o template. A acurácia em escala é medida no benchmark, não aqui.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import numpy as np
import pytest

from poker_arena.vision import ocr
from poker_arena.vision.recognize import recognize_table
from poker_arena.vision.synth import CANONICAL, render_table

requires_ocr = pytest.mark.skipif(not ocr.available(), reason="RapidOCR não instalado")


@requires_ocr
def test_le_o_pote_exato_por_ocr():
    img, truth = render_table(seed=7, style=CANONICAL, with_seats=True, n_board=5)
    st = recognize_table(img, ocr_numbers=True)
    assert st.pot == truth["pot"]
    assert st.pot_source == "ocr"


@requires_ocr
def test_le_stacks_dos_jogadores():
    # deep_stacks=True: caminho de análise (offline) lê as fichas por assento
    img, _ = render_table(seed=3, style=CANONICAL, with_seats=True, n_board=3)
    st = recognize_table(img, ocr_numbers=True, deep_stacks=True)
    assert st.stacks and len(st.stacks) >= 2  # leu fichas de vários assentos


@requires_ocr
def test_caminho_rapido_nao_le_stacks_mas_le_pote():
    # padrão (deep_stacks=False, <=4s): pote sim, stacks não (não críticos p/ decisão)
    img, truth = render_table(seed=7, style=CANONICAL, with_seats=True, n_board=5)
    st = recognize_table(img, ocr_numbers=True)
    assert st.pot == truth["pot"] and st.pot_source == "ocr"
    assert st.stacks is None


def test_interpret_separa_pote_de_stack_por_geometria():
    # pote central + um número junto de um assento -> pote vira pot, o outro vira stack
    W, H = 900, 600
    nums = [
        (1500, W * 0.5, H * 0.32, 1.0),  # central -> pote
        (250, W * 0.12, H * 0.66, 1.0),
    ]  # junto do assento 0 -> stack
    seats = [(W * 0.12, H * 0.64)]
    sn = ocr.interpret(nums, W, H, card_boxes=[], seat_centers=seats)
    assert sn.pot == 1500
    assert sn.stacks == {0: 250}
    assert sn.stack_confidences == {0: 1.0}


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


def test_fast_path_abstains_when_multiple_central_numbers_are_ambiguous(monkeypatch):
    monkeypatch.setattr(
        ocr,
        "read_numbers",
        lambda _crop: [(100, 200.0, 80.0, 0.99), (250, 240.0, 100.0, 0.98)],
    )
    rgb = np.zeros((600, 900, 3), np.uint8)
    result = ocr.read_screen(rgb, 900, 600)
    assert result.pot is None and result.pot_conf == 0.0


def test_fast_path_excludes_number_inside_selected_card_box(monkeypatch):
    monkeypatch.setattr(ocr, "read_numbers", lambda _crop: [(9, 234.0, 180.0, 0.99)])
    rgb = np.zeros((600, 900, 3), np.uint8)
    # Crop origin is (216, 60), therefore OCR center maps to (450, 240).
    result = ocr.read_screen(rgb, 900, 600, card_boxes=[(420, 210, 60, 80)])
    assert result.pot is None


def test_read_roi_rejects_low_confidence_amount(monkeypatch):
    def engine(_image):
        return [([[0, 0]], "100", 0.2)], None

    monkeypatch.setattr(ocr, "_engine", lambda: engine)
    rgb = np.zeros((100, 100, 3), np.uint8)
    assert ocr.read_roi(rgb, 50, 50, 20, 20) is None


def test_broken_installed_ocr_raises_typed_initialization_error(monkeypatch):
    class BrokenRapidOCR:
        def __init__(self):
            raise RuntimeError("corrupt runtime")

    ocr._engine_cached.cache_clear()
    monkeypatch.setitem(
        sys.modules,
        "rapidocr_onnxruntime",
        SimpleNamespace(RapidOCR=BrokenRapidOCR),
    )
    with pytest.raises(ocr.OCREngineInitializationError, match="initialization"):
        ocr._engine_cached()
