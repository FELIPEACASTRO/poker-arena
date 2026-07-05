"""Reconhecedor F2: o modelo TREINADO (YOLO11n ONNX) que generaliza pra QUALQUER tela.

A F1 (template + blob de cor) prova o pipeline mas é calibrada num estilo. Esta é a F2:
o detector treinado só em sintético que, na medição held-out (estilos nunca vistos),
bate mAP50 ~99%. Mesma SAÍDA da F1 (`RecognizedState`) — então o sanity-check, o
endpoint e o copiloto não mudam: só troca QUEM lê a imagem.

Espelha o padrão do Expert (bots): modelo em `models/`, override por env, import tardio
do onnxruntime e AUSÊNCIA graciosa (se o .onnx não está lá, o backend usa a F1). Aceita
o modelo de 52 classes (só cartas) OU o de 54 (cartas + jogador + botão) — nesse caso
também conta participantes e deriva a posição, como a F1 faz por geometria.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from .recognize import RecognizedState, _gray, _read_numbers
from .seats import derive_position
from .synth import RANKS, SUITS

CARD_NAMES = [r + s for r in RANKS for s in SUITS]  # 52, MESMA ordem do notebook F2
SEAT_CLS, BUTTON_CLS = 52, 53  # só no modelo de 54 classes
_IMGSZ = 640
_CONF = 0.35
_IOU = 0.5


_MODEL_NAMES = ("poker_vision.onnx", "table_yolo11n.onnx")  # nome canônico + o que o HF publica


def _pick_model(models: Path) -> Path:
    """Primeiro nome conhecido que existir em `models/` (aceita o .onnx do HF sem
    renomear); senão o nome canônico (pra mensagem de erro quando nenhum existe)."""
    for name in _MODEL_NAMES:
        if (models / name).exists():
            return models / name
    return models / _MODEL_NAMES[0]


def vision_model_path() -> Path:
    """Onde o backend procura o detector treinado. Override via POKER_VISION_MODEL."""
    env = os.environ.get("POKER_VISION_MODEL")
    if env:
        return Path(env)
    return _pick_model(Path(__file__).resolve().parents[2] / "models")


def vision_model_available() -> bool:
    return vision_model_path().exists()


def _letterbox(rgb: np.ndarray, size: int = _IMGSZ) -> tuple[np.ndarray, float, float, float]:
    """Redimensiona mantendo a proporção e preenche pra (size,size) com cinza 114 —
    exatamente o pré-processo do Ultralytics. Devolve (imagem, ratio, dw, dh)."""
    h, w = rgb.shape[:2]
    ratio = min(size / h, size / w)
    nh, nw = round(h * ratio), round(w * ratio)
    resized = np.asarray(Image.fromarray(rgb).resize((nw, nh), Image.BILINEAR))
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    dw, dh = (size - nw) / 2, (size - nh) / 2  # padding simétrico (metade de cada lado)
    top, left = int(round(dh - 0.1)), int(round(dw - 0.1))
    canvas[top : top + nh, left : left + nw] = resized
    return canvas, ratio, left, top


def _nms(boxes: np.ndarray, scores: np.ndarray, iou_thr: float) -> list[int]:
    """Non-max suppression (numpy puro). boxes em xyxy. Devolve índices mantidos."""
    if len(boxes) == 0:
        return []
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1).clip(0) * (y2 - y1).clip(0)
    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = int(order[0])
        keep.append(i)
        if order.size == 1:
            break
        rest = order[1:]
        xx1 = np.maximum(x1[i], x1[rest])
        yy1 = np.maximum(y1[i], y1[rest])
        xx2 = np.minimum(x2[i], x2[rest])
        yy2 = np.minimum(y2[i], y2[rest])
        inter = (xx2 - xx1).clip(0) * (yy2 - yy1).clip(0)
        iou = inter / (areas[i] + areas[rest] - inter + 1e-9)
        order = rest[iou <= iou_thr]
    return keep


def _decode(
    output: np.ndarray, ratio: float, dw: float, dh: float, conf: float, iou: float
) -> list[tuple[int, float, float, float, float, float]]:
    """Saída YOLO (1, 4+nc, N) -> deteccoes (cls, conf, x1,y1,x2,y2) em pixels da imagem
    ORIGINAL. Desfaz o letterbox e aplica NMS por classe (padrão do Ultralytics)."""
    out = output[0]  # (4+nc, N)
    if out.shape[0] < out.shape[1]:  # (4+nc, N) -> (N, 4+nc)
        out = out.T
    boxes_cxcywh, scores_all = out[:, :4], out[:, 4:]
    cls = scores_all.argmax(1)
    conf_v = scores_all.max(1)
    m = conf_v >= conf
    boxes_cxcywh, cls, conf_v = boxes_cxcywh[m], cls[m], conf_v[m]
    if len(boxes_cxcywh) == 0:
        return []
    cx, cy, w, h = boxes_cxcywh.T
    xyxy = np.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], 1)
    xyxy[:, [0, 2]] = (xyxy[:, [0, 2]] - dw) / ratio  # desfaz pad + escala
    xyxy[:, [1, 3]] = (xyxy[:, [1, 3]] - dh) / ratio
    cards, others = [], []
    for c in np.unique(cls):  # NMS por classe (como o Ultralytics com agnostic_nms=False)
        idx = np.where(cls == c)[0]
        for k in _nms(xyxy[idx], conf_v[idx], iou):
            j = idx[k]
            x1, y1, x2, y2 = xyxy[j]
            det = (int(c), float(conf_v[j]), float(x1), float(y1), float(x2), float(y2))
            (cards if c < 52 else others).append(det)
    # NMS CLASS-AGNOSTIC entre cartas: mata duplicatas de classes DIFERENTES na mesma
    # carta (ex.: 'As' e 'Ks' no mesmo retângulo) antes de qualquer corte top-k
    if cards:
        cb = np.array([d[2:] for d in cards], dtype=np.float32)
        cs = np.array([d[1] for d in cards], dtype=np.float32)
        cards = [cards[k] for k in _nms(cb, cs, iou)]
    return cards + others


class OnnxRecognizer:
    """Sessão ONNX carregada uma vez; `recognize(img)` -> RecognizedState (como a F1)."""

    def __init__(self, model_path: Path) -> None:
        import onnxruntime as ort  # import tardio: onnxruntime só quando a F2 é usada

        self._session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        self._input = self._session.get_inputs()[0].name

    def recognize(
        self, img: Image.Image, ocr_numbers: bool = False, deep_stacks: bool = False
    ) -> RecognizedState:
        rgb = np.asarray(img.convert("RGB"))
        H, W = rgb.shape[:2]
        canvas, ratio, dw, dh = _letterbox(rgb)
        blob = canvas.astype(np.float32).transpose(2, 0, 1)[None] / 255.0  # (1,3,640,640)
        out = self._session.run(None, {self._input: blob})[0]
        dets = _decode(np.asarray(out), ratio, dw, dh, _CONF, _IOU)

        button = None  # None (não []): sem botão detectado -> derive_position abstém da posição
        hole, board, seats, confs, card_boxes = [], [], [], [], []
        for c, cf, x1, y1, x2, y2 in dets:
            cxp, cyp = (x1 + x2) / 2, (y1 + y2) / 2
            if c < 52:
                confs.append(cf)
                card_boxes.append((int(x1), int(y1), int(x2 - x1), int(y2 - y1)))
                (hole if cyp > H * 0.66 else board).append((cxp, cf, CARD_NAMES[c]))
            elif c == SEAT_CLS:
                seats.append((cxp, cyp))
            elif c == BUTTON_CLS:
                button = (cxp, cyp)
        # corte top-k pela CONFIANÇA (não pela posição), depois ordena L->R por x
        hole_top = sorted(hole, key=lambda t: t[1], reverse=True)[:2]
        board_top = sorted(board, key=lambda t: t[1], reverse=True)[:5]
        hole_sorted = [name for _, _, name in sorted(hole_top)]
        board_sorted = [name for _, _, name in sorted(board_top)]

        hx = float(np.mean([p for p, _, _ in hole_top])) if hole_top else W / 2
        hero = (hx, H * 0.82)
        n_players, position = derive_position(seats, hero, button) if len(seats) >= 2 else (0, "")

        pot, potc, stacks, src = _read_numbers(
            rgb, _gray(img), card_boxes, seats, ocr_numbers, deep_stacks)
        if pot is not None:
            confs.append(potc)
        return RecognizedState(
            hole=hole_sorted, board=board_sorted, pot=pot,
            n_cards=len(hole_sorted) + len(board_sorted),
            confidence=round(float(np.mean(confs)) if confs else 0.0, 3),
            n_players=n_players, position=position, stacks=stacks, pot_source=src,
        )


@lru_cache(maxsize=2)
def _cached_recognizer(path: str, mtime: float) -> OnnxRecognizer:
    return OnnxRecognizer(Path(path))


def recognize_table_onnx(
    img: Image.Image, ocr_numbers: bool = False, deep_stacks: bool = False
) -> RecognizedState:
    """Reconhece com o modelo TREINADO (F2). Requer o .onnx em models/ (ou POKER_VISION_MODEL).
    A sessão é cacheada por (caminho, mtime) — recarrega sozinha se você trocar o modelo."""
    path = vision_model_path()
    if not path.exists():
        raise FileNotFoundError(
            f"detector treinado não encontrado em {path}; rode o notebook 08 e coloque o "
            "poker_vision.onnx lá (ou defina POKER_VISION_MODEL). Sem ele, use a F1."
        )
    rec = _cached_recognizer(str(path), path.stat().st_mtime)
    return rec.recognize(img, ocr_numbers, deep_stacks)
