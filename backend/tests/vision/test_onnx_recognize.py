"""Reconhecedor F2 (ONNX treinado): pré-processo, decode YOLO e o plumbing da sessão.

Não dá pra baixar o modelo treinado aqui, então: (1) as funções puras (letterbox/NMS/
decode) são testadas com tensores sintéticos de coordenadas CONHECIDAS; (2) o caminho
completo (sessão ONNX -> RecognizedState) é testado com um ONNX minúsculo de saída
CONSTANTE que codifica deteccoes conhecidas — prova a fiação sem depender dos pesos.
"""

from __future__ import annotations

import numpy as np
import onnx
import pytest
from onnx import TensorProto, helper
from PIL import Image

from poker_arena.model_artifacts import ModelArtifactUnavailable
from poker_arena.vision.onnx_recognize import (
    CARD_NAMES,
    OnnxRecognizer,
    _decode,
    _letterbox,
    _nms,
    _select_button,
    recognize_table_onnx,
    vision_model_available,
    vision_model_path,
)
from tests.helpers.model_manifest import approve_vision


def _yolo_output(dets, W, H, nc=52, n_anchors=300):
    """Monta uma saída YOLO (1, 4+nc, N) com deteccoes em coords ORIGINAIS.
    N (âncoras) > 4+nc, como no modelo real (8400 >> 56) — decode acha o eixo certo."""
    _, ratio, dw, dh = _letterbox(np.zeros((H, W, 3), np.uint8))
    out = np.zeros((1, 4 + nc, n_anchors), np.float32)
    for a, (ox, oy, ow, oh, cls, sc) in enumerate(dets):
        out[0, 0, a] = ox * ratio + dw
        out[0, 1, a] = oy * ratio + dh
        out[0, 2, a] = ow * ratio
        out[0, 3, a] = oh * ratio
        out[0, 4 + cls, a] = sc
    return out, ratio, dw, dh


def _const_onnx(array: np.ndarray, path, metadata: dict[str, str] | None = None) -> None:
    """Escreve um ONNX que ignora a entrada e devolve SEMPRE `array` (teste de fiação)."""
    x = helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, 640, 640])
    y = helper.make_tensor_value_info("output0", TensorProto.FLOAT, list(array.shape))
    const = helper.make_node(
        "Constant",
        [],
        ["output0"],
        value=helper.make_tensor("v", TensorProto.FLOAT, array.shape, array.flatten().tolist()),
    )
    graph = helper.make_graph([const], "const_yolo", [x], [y])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 9
    nc = array.shape[1] - 4
    manifest_names = CARD_NAMES + (["seat", "button"] if nc == 54 else [])
    if metadata is None:
        names = manifest_names
        metadata = {"names": repr({i: name for i, name in enumerate(names)})}
    if metadata:
        helper.set_model_props(model, metadata)
    onnx.save(model, str(path))
    approve_vision(path, list(array.shape), manifest_names)


# ---------- funções puras ----------
def test_letterbox_preenche_ate_640_mantendo_proporcao():
    canvas, ratio, dw, dh = _letterbox(np.zeros((600, 900, 3), np.uint8))
    assert canvas.shape == (640, 640, 3)
    assert ratio == pytest.approx(640 / 900, abs=1e-3)  # limitado pela largura
    assert dw == 0 and dh > 0  # padding vertical (imagem mais larga que alta)


def test_nms_suprime_caixas_sobrepostas():
    boxes = np.array([[10, 10, 50, 50], [12, 12, 52, 52], [200, 200, 240, 240]], float)
    scores = np.array([0.9, 0.8, 0.7])
    keep = _nms(boxes, scores, 0.5)
    assert keep == [0, 2]  # a segunda (sobreposta à primeira) some


def test_button_selection_prefers_highest_confidence_and_abstains_on_conflict():
    assert _select_button([(0.95, 100.0, 100.0), (0.40, 800.0, 500.0)], (900, 600)) == (
        100.0,
        100.0,
    )
    assert _select_button([(0.95, 100.0, 100.0), (0.90, 800.0, 500.0)], (900, 600)) is None


def test_decode_recupera_coordenadas_e_classes_originais():
    out, ratio, dw, dh = _yolo_output(
        [
            (450, 300, 62, 87, CARD_NAMES.index("As"), 0.9),
            (404, 470, 62, 87, CARD_NAMES.index("Kh"), 0.9),
            (496, 470, 62, 87, CARD_NAMES.index("Qd"), 0.9),
        ],
        900,
        600,
    )
    dets = _decode(out, ratio, dw, dh, 0.35, 0.5)
    got = {CARD_NAMES[c]: ((x1 + x2) / 2, (y1 + y2) / 2) for c, _, x1, y1, x2, y2 in dets}
    assert set(got) == {"As", "Kh", "Qd"}
    assert got["As"][0] == pytest.approx(450, abs=1.5)
    assert got["As"][1] == pytest.approx(300, abs=1.5)
    assert got["Kh"][1] == pytest.approx(470, abs=1.5)


def test_decode_ignora_deteccoes_abaixo_do_limiar():
    out, ratio, dw, dh = _yolo_output([(450, 300, 62, 87, 0, 0.10)], 900, 600)
    assert _decode(out, ratio, dw, dh, 0.35, 0.5) == []


# ---------- clipping / NMS fisico ----------
def test_decode_clips_boxes_to_original_image_bounds():
    out, ratio, dw, dh = _yolo_output([(5, 5, 40, 40, CARD_NAMES.index("As"), 0.9)], 900, 600)
    det = _decode(out, ratio, dw, dh, 0.35, 0.5, image_size=(900, 600))[0]
    _, _, x1, y1, x2, y2 = det
    assert (x1, y1) == (0.0, 0.0)
    assert x2 <= 900 and y2 <= 600


def test_cross_class_nms_preserves_distinct_partially_overlapping_cards():
    out, ratio, dw, dh = _yolo_output(
        [
            (430, 470, 62, 87, CARD_NAMES.index("As"), 0.95),
            (445, 470, 62, 87, CARD_NAMES.index("Ks"), 0.94),
        ],
        900,
        600,
    )
    dets = _decode(out, ratio, dw, dh, 0.35, 0.5)
    assert {CARD_NAMES[d[0]] for d in dets} == {"As", "Ks"}


# ---------- caminho completo com ONNX minúsculo ----------
def test_recognize_52_classes_via_sessao_onnx(tmp_path):
    W, H = 900, 600
    out, *_ = _yolo_output(
        [
            (450, 300, 62, 87, CARD_NAMES.index("As"), 0.9),  # board (centro)
            (404, 470, 62, 87, CARD_NAMES.index("Kh"), 0.9),  # hole (embaixo)
            (496, 470, 62, 87, CARD_NAMES.index("Qd"), 0.9),
        ],
        W,
        H,
    )
    p = tmp_path / "m.onnx"
    _const_onnx(out, p)
    st = OnnxRecognizer(p).recognize(Image.new("RGB", (W, H), (20, 90, 60)))
    assert set(st.hole) == {"Kh", "Qd"}
    assert st.board == ["As"]
    assert st.n_cards == 3
    assert st.n_players == 0  # modelo de 52 classes não detecta jogadores


def test_rejects_model_with_incompatible_class_metadata(tmp_path):
    out, *_ = _yolo_output([], 900, 600)
    p = tmp_path / "wrong_names.onnx"
    wrong = {i: name for i, name in enumerate(CARD_NAMES)}
    wrong[0] = "not-a-card"
    _const_onnx(out, p, {"names": repr(wrong)})
    with pytest.raises(ValueError, match="metadata"):
        OnnxRecognizer(p)


def test_rejects_model_without_class_metadata(tmp_path):
    out, *_ = _yolo_output([], 900, 600)
    p = tmp_path / "missing_names.onnx"
    _const_onnx(out, p, {})
    with pytest.raises(ValueError, match="metadata"):
        OnnxRecognizer(p)


def test_recognize_54_classes_conta_jogadores_e_deriva_posicao(tmp_path):
    import math

    W, H = 900, 600
    dets = [
        (404, 470, 62, 87, CARD_NAMES.index("Ah"), 0.9),  # hole
        (496, 470, 62, 87, CARD_NAMES.index("Ad"), 0.9),
    ]
    # 6 assentos ao redor; herói embaixo (assento 0); botão no herói -> BTN
    for i in range(6):
        ang = math.radians(90 + i * 60)
        sx, sy = W / 2 + W * 0.40 * math.cos(ang), H / 2 + H * 0.44 * math.sin(ang)
        dets.append((sx, sy, 48, 48, 52, 0.9))  # classe 52 = seat
    dets.append((W / 2 + 30, H / 2 + H * 0.44 - 10, 24, 24, 53, 0.9))  # botão perto do herói
    out, *_ = _yolo_output(dets, W, H, nc=54)
    p = tmp_path / "m54.onnx"
    _const_onnx(out, p)
    st = OnnxRecognizer(p).recognize(Image.new("RGB", (W, H), (20, 90, 60)))
    assert set(st.hole) == {"Ah", "Ad"}
    assert st.n_players == 6
    assert st.position == "BTN"  # botão no assento do herói


def test_corte_topk_por_confianca_nao_por_posicao_x(tmp_path):
    # cenário do review adversarial: 3 deteccoes na região do herói — um falso-positivo
    # MAIS À ESQUERDA (conf baixa) + 2 cartas certas à direita (conf alta). O corte tem
    # de ficar com as de MAIOR CONFIANÇA, não com as mais à esquerda.
    W, H = 900, 600
    dets = [
        (150, 470, 62, 87, CARD_NAMES.index("2c"), 0.40),  # falso-positivo, x baixo
        (404, 470, 62, 87, CARD_NAMES.index("As"), 0.95),  # carta certa
        (496, 470, 62, 87, CARD_NAMES.index("Ks"), 0.93),
    ]  # carta certa
    out, *_ = _yolo_output(dets, W, H)
    p = tmp_path / "topk.onnx"
    _const_onnx(out, p)
    st = OnnxRecognizer(p).recognize(Image.new("RGB", (W, H), (20, 90, 60)))
    assert set(st.hole) == {"As", "Ks"}  # o falso-positivo 2c (mais à esquerda) foi descartado


def test_ocr_masks_only_cards_that_survive_topk(monkeypatch, tmp_path):
    import poker_arena.vision.onnx_recognize as module

    W, H = 900, 600
    dets = [
        (150, 470, 62, 87, CARD_NAMES.index("2c"), 0.40),
        (404, 470, 62, 87, CARD_NAMES.index("As"), 0.95),
        (496, 470, 62, 87, CARD_NAMES.index("Ks"), 0.93),
    ]
    out, *_ = _yolo_output(dets, W, H)
    path = tmp_path / "ocr_masks.onnx"
    _const_onnx(out, path)
    captured = {}

    def fake_numbers(_rgb, _gray, boxes, _seats, _ocr, _deep):
        captured["boxes"] = boxes
        return None, 0.0, None, None, "template"

    monkeypatch.setattr(module, "_read_numbers", fake_numbers)
    OnnxRecognizer(path).recognize(Image.new("RGB", (W, H), (20, 90, 60)))
    assert len(captured["boxes"]) == 2
    assert all(box[0] > 300 for box in captured["boxes"])


def test_hero_seat_uses_actual_hole_card_centroid(monkeypatch, tmp_path):
    import poker_arena.vision.onnx_recognize as module

    W, H = 900, 600
    dets = [
        (180, 410, 62, 87, CARD_NAMES.index("As"), 0.95),
        (250, 410, 62, 87, CARD_NAMES.index("Ks"), 0.93),
        (210, 405, 48, 48, 52, 0.9),
        (700, 500, 48, 48, 52, 0.9),
        (210, 405, 24, 24, 53, 0.9),
    ]
    out, *_ = _yolo_output(dets, W, H, nc=54)
    path = tmp_path / "hero_centroid.onnx"
    _const_onnx(out, path)
    captured = {}

    def fake_derive(seats, hero, button):
        captured.update(seats=seats, hero=hero, button=button)
        return len(seats), "BTN"

    monkeypatch.setattr(module, "derive_position", fake_derive)
    OnnxRecognizer(path).recognize(Image.new("RGB", (W, H), (20, 90, 60)))
    assert captured["hero"] == pytest.approx((215.0, 410.0), abs=1.5)


def test_nms_class_agnostic_mata_duplicata_na_mesma_carta(tmp_path):
    # duas CLASSES diferentes disparadas na MESMA carta física (mesmo retângulo) —
    # o NMS por-classe não remove; o class-agnostic entre cartas remove a de menor conf.
    W, H = 900, 600
    dets = [
        (404, 470, 62, 87, CARD_NAMES.index("As"), 0.95),  # carta real
        (405, 471, 62, 87, CARD_NAMES.index("Ks"), 0.60),  # duplicata sobreposta
        (496, 470, 62, 87, CARD_NAMES.index("Qd"), 0.92),
    ]  # outra carta
    out, *_ = _yolo_output(dets, W, H)
    p = tmp_path / "dup.onnx"
    _const_onnx(out, p)
    st = OnnxRecognizer(p).recognize(Image.new("RGB", (W, H), (20, 90, 60)))
    assert set(st.hole) == {"As", "Qd"}  # Ks sobreposto a As foi suprimido


def test_assentos_sem_botao_nao_crasham_a_f2(tmp_path):
    # regressão: com >=2 assentos mas SEM dealer button (disco pequeno abaixo do limiar),
    # button ficava [] e derive_position estourava IndexError -> HTTP 500. Agora abstém.
    import math

    W, H = 900, 600
    dets = [
        (404, 470, 62, 87, CARD_NAMES.index("Ah"), 0.9),
        (496, 470, 62, 87, CARD_NAMES.index("Kd"), 0.9),
    ]
    for i in range(5):  # 5 assentos, NENHUM botão (classe 53 ausente)
        ang = math.radians(90 + i * 72)
        sx, sy = W / 2 + W * 0.40 * math.cos(ang), H / 2 + H * 0.44 * math.sin(ang)
        dets.append((sx, sy, 48, 48, 52, 0.9))
    out, *_ = _yolo_output(dets, W, H, nc=54)
    p = tmp_path / "nobtn.onnx"
    _const_onnx(out, p)
    st = OnnxRecognizer(p).recognize(Image.new("RGB", (W, H), (20, 90, 60)))  # não pode crashar
    assert st.n_players == 5
    assert st.position == ""  # sem botão -> sem posição, mas conta os jogadores


# ---------- disponibilidade / fallback ----------
def test_ausencia_do_modelo_e_graciosa(monkeypatch, tmp_path):
    monkeypatch.setenv("POKER_VISION_MODEL", str(tmp_path / "nao_existe.onnx"))
    assert not vision_model_available()
    assert vision_model_path().name == "nao_existe.onnx"
    with pytest.raises(FileNotFoundError):
        recognize_table_onnx(Image.new("RGB", (100, 100)))


def test_existencia_sem_manifesto_nao_ativa_f2(monkeypatch, tmp_path):
    path = tmp_path / "poker_vision.onnx"
    path.write_bytes(b"present-but-unapproved")
    monkeypatch.setenv("POKER_VISION_MODEL", str(path))
    assert not vision_model_available()
    with pytest.raises(ModelArtifactUnavailable, match="manifest"):
        recognize_table_onnx(Image.new("RGB", (100, 100)))


def test_modelo_aprovado_e_hash_pinned_ativa_f2(monkeypatch, tmp_path):
    out, *_ = _yolo_output([], 100, 100)
    path = tmp_path / "poker_vision.onnx"
    _const_onnx(out, path)
    monkeypatch.setenv("POKER_VISION_MODEL", str(path))
    assert vision_model_available()
    state = recognize_table_onnx(Image.new("RGB", (100, 100)))
    assert state.n_cards == 0


def test_aceita_o_nome_do_arquivo_publicado_pelo_hf(tmp_path):
    # o notebook publica como table_yolo11n.onnx; o backend acha sem renomear
    from poker_arena.vision.onnx_recognize import _pick_model

    assert _pick_model(tmp_path).name == "poker_vision.onnx"  # nenhum existe -> canônico
    (tmp_path / "table_yolo11n.onnx").write_bytes(b"x")
    assert _pick_model(tmp_path).name == "table_yolo11n.onnx"  # acha o do HF
    (tmp_path / "poker_vision.onnx").write_bytes(b"x")
    assert _pick_model(tmp_path).name == "poker_vision.onnx"  # canônico tem prioridade


def test_alias_aprovado_prevalece_sobre_canonico_so_existente(tmp_path):
    from poker_arena.vision.onnx_recognize import _pick_model

    alias = tmp_path / "table_yolo11n.onnx"
    out, *_ = _yolo_output([], 100, 100)
    _const_onnx(out, alias)  # manifesto declara e aprova somente o alias
    (tmp_path / "poker_vision.onnx").write_bytes(b"presente-sem-entrada")
    assert _pick_model(tmp_path) == alias
