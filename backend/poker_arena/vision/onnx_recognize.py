"""Reconhecedor F2: inferência e validação de contrato do detector YOLO11n ONNX.

A F1 é calibrada num estilo sintético. O artefato F2 instalado declara 54 classes
(52 cartas, assento e botão), mas não contém métricas reais anexadas e não deve ser
descrito como universal. A saída usa `RecognizedState` e só pode chegar ao Copiloto
depois do gate de sanidade/confiança.

Espelha o padrão do Expert (bots): modelo em `models/`, override por env, import tardio
do onnxruntime e AUSÊNCIA/REPROVAÇÃO graciosa (o backend usa a F1). O arquivo só é
carregado após manifesto aprovado, hash, governança e contrato. Aceita
o modelo de 52 classes (só cartas) OU o de 54 (cartas + jogador + botão) — nesse caso
também conta participantes e deriva a posição, como a F1 faz por geometria. Metadados
de classes incompatíveis são rejeitados antes da primeira inferência.
"""

from __future__ import annotations

import ast
import os
import threading
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from ..model_artifacts import (
    ModelArtifactUnavailable,
    VerifiedModelArtifact,
    model_artifact_available,
    model_manifest_path,
    revalidate_model_artifact_identity,
    verify_model_artifact,
    verify_runtime_contract,
)
from .recognize import RecognizedState, _cards_force_abstention, _gray, _read_numbers
from .seats import derive_position
from .synth import RANKS, SUITS

CARD_NAMES = [r + s for r in RANKS for s in SUITS]  # 52, MESMA ordem do notebook F2
SEAT_CLS, BUTTON_CLS = 52, 53  # só no modelo de 54 classes
_IMGSZ = 640
_CONF = 0.35
_IOU = 0.5
_BUTTON_AMBIGUITY_RATIO = 0.8
_BUTTON_CONFLICT_DIAGONAL = 0.08

Detection = tuple[int, float, float, float, float, float]
Box = tuple[int, int, int, int]
Point = tuple[float, float]
CardCandidate = tuple[float, float, float, str, Box]  # cx, cy, confidence, name, box


_MODEL_NAMES = ("poker_vision.onnx", "table_yolo11n.onnx")  # nome canônico + o que o HF publica


def _pick_model(models: Path) -> Path:
    """Prefere o primeiro candidato aprovado; presença sozinha só define a mensagem."""
    present = [models / name for name in _MODEL_NAMES if (models / name).exists()]
    for candidate in present:
        if model_artifact_available(
            candidate,
            "vision",
            manifest_path=model_manifest_path(candidate, "POKER_VISION_MANIFEST"),
        ):
            return candidate
    if present:
        return present[0]
    return models / _MODEL_NAMES[0]


def vision_model_path() -> Path:
    """Onde o backend procura o detector treinado. Override via POKER_VISION_MODEL."""
    env = os.environ.get("POKER_VISION_MODEL")
    if env:
        return Path(env)
    return _pick_model(Path(__file__).resolve().parents[2] / "models")


def vision_model_manifest_path() -> Path:
    """Manifesto obrigatório do detector; acompanha também overrides externos."""
    return model_manifest_path(vision_model_path(), "POKER_VISION_MANIFEST")


def vision_model_available() -> bool:
    try:
        _resolve_vision_artifact()
    except (FileNotFoundError, ModelArtifactUnavailable):
        return False
    return True


def _resolve_vision_artifact() -> VerifiedModelArtifact:
    """Resolve and verify the deployable F2 artifact once for one inference attempt."""
    env = os.environ.get("POKER_VISION_MODEL")
    if env:
        candidates = [Path(env)]
    else:
        models = Path(__file__).resolve().parents[2] / "models"
        candidates = [models / name for name in _MODEL_NAMES if (models / name).exists()]
    if not candidates:
        missing = (
            Path(env) if env else Path(__file__).resolve().parents[2] / "models" / _MODEL_NAMES[0]
        )
        raise FileNotFoundError(f"detector treinado não encontrado em {missing}")

    first_error: ModelArtifactUnavailable | None = None
    for candidate in candidates:
        if not candidate.is_file():
            if env:
                raise FileNotFoundError(f"detector treinado não encontrado em {candidate}")
            continue
        try:
            return verify_model_artifact(
                candidate,
                "vision",
                manifest_path=model_manifest_path(candidate, "POKER_VISION_MANIFEST"),
            )
        except ModelArtifactUnavailable as exc:
            if first_error is None:
                first_error = exc
    if first_error is not None:
        raise first_error
    raise FileNotFoundError("nenhum detector treinado candidato está disponível")


def _letterbox(rgb: np.ndarray, size: int = _IMGSZ) -> tuple[np.ndarray, float, float, float]:
    """Redimensiona mantendo a proporção e preenche pra (size,size) com cinza 114 —
    exatamente o pré-processo do Ultralytics. Devolve (imagem, ratio, dw, dh)."""
    h, w = rgb.shape[:2]
    ratio = min(size / h, size / w)
    nh, nw = round(h * ratio), round(w * ratio)
    resized = np.asarray(Image.fromarray(rgb).resize((nw, nh), Image.Resampling.BILINEAR))
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
    output: np.ndarray,
    ratio: float,
    dw: float,
    dh: float,
    conf: float,
    iou: float,
    image_size: tuple[int, int] | None = None,
) -> list[Detection]:
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
    finite = np.isfinite(xyxy).all(axis=1) & np.isfinite(conf_v)
    xyxy, cls, conf_v = xyxy[finite], cls[finite], conf_v[finite]
    if image_size is not None:
        image_w, image_h = image_size
        xyxy[:, [0, 2]] = np.clip(xyxy[:, [0, 2]], 0.0, float(image_w))
        xyxy[:, [1, 3]] = np.clip(xyxy[:, [1, 3]], 0.0, float(image_h))
    nonempty = (xyxy[:, 2] > xyxy[:, 0]) & (xyxy[:, 3] > xyxy[:, 1])
    xyxy, cls, conf_v = xyxy[nonempty], cls[nonempty], conf_v[nonempty]
    cards: list[Detection] = []
    others: list[Detection] = []
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
        # Only near-identical cross-class boxes are duplicates. A lower threshold can
        # erase two genuinely overlapping physical cards in a fanned hand.
        cards = [cards[k] for k in _nms(cb, cs, max(iou, 0.85))]
    return cards + others


def _select_button(
    candidates: list[tuple[float, float, float]], image_size: tuple[int, int]
) -> Point | None:
    """Choose the strongest button, abstaining on similarly strong spatial conflicts."""

    if not candidates:
        return None
    ranked = sorted(candidates, key=lambda item: item[0], reverse=True)
    best_conf, best_x, best_y = ranked[0]
    width, height = image_size
    conflict_distance2 = (_BUTTON_CONFLICT_DIAGONAL * float(np.hypot(width, height))) ** 2
    for confidence, x, y in ranked[1:]:
        if confidence < best_conf * _BUTTON_AMBIGUITY_RATIO:
            continue
        if (x - best_x) ** 2 + (y - best_y) ** 2 > conflict_distance2:
            return None
    return best_x, best_y


class OnnxRecognizer:
    """Sessão ONNX carregada uma vez; `recognize(img)` -> RecognizedState (como a F1)."""

    def __init__(
        self,
        model_path: Path,
        *,
        manifest_path: str | Path | None = None,
        artifact: VerifiedModelArtifact | None = None,
        allow_evaluation_candidate: bool = False,
    ) -> None:
        import onnxruntime as ort  # import tardio: onnxruntime só quando a F2 é usada

        resolved_manifest = (
            Path(manifest_path)
            if manifest_path is not None
            else model_manifest_path(model_path, "POKER_VISION_MANIFEST")
        )
        if artifact is None:
            artifact = verify_model_artifact(model_path, "vision", manifest_path=resolved_manifest)
        elif (
            artifact.kind != "vision"
            or (
                artifact.usage != "deployment"
                and not (allow_evaluation_candidate and artifact.usage == "evaluation")
            )
            or artifact.path != model_path.resolve()
            or artifact.manifest_path != resolved_manifest.resolve()
        ):
            raise ModelArtifactUnavailable(
                "receipt_mismatch", "vision loader received a receipt for another artifact"
            )
        revalidate_model_artifact_identity(artifact)
        try:
            self._session = ort.InferenceSession(
                str(artifact.path), providers=["CPUExecutionProvider"]
            )
        except Exception as exc:  # noqa: BLE001 - normalize runtime load as gate rejection
            raise ModelArtifactUnavailable("runtime_load_failed", str(exc)) from exc
        revalidate_model_artifact_identity(artifact)
        inputs = self._session.get_inputs()
        outputs = self._session.get_outputs()
        verify_runtime_contract(artifact, inputs, outputs)
        if len(inputs) != 1 or len(outputs) != 1:
            raise ValueError("vision model contract requires exactly one input and one output")
        shape = inputs[0].shape
        if len(shape) != 4:
            raise ValueError(f"vision model input must be NCHW, got {shape!r}")
        for actual, expected_dimension, label in (
            (shape[1], 3, "channels"),
            (shape[2], _IMGSZ, "height"),
            (shape[3], _IMGSZ, "width"),
        ):
            if isinstance(actual, int) and actual != expected_dimension:
                raise ValueError(
                    f"vision model input {label} must be {expected_dimension}, got {actual}"
                )

        out_shape = outputs[0].shape
        class_count = None
        if len(out_shape) == 3:
            for dim in (out_shape[1], out_shape[2]):
                if isinstance(dim, int) and dim in (56, 58):
                    class_count = dim - 4
                    break
        if class_count is None and all(isinstance(dim, int) for dim in out_shape):
            raise ValueError(f"vision model output must encode 52 or 54 classes, got {out_shape!r}")

        raw_names = self._session.get_modelmeta().custom_metadata_map.get("names")
        if not raw_names:
            raise ValueError("missing class metadata in vision model")
        if raw_names:
            try:
                parsed = ast.literal_eval(raw_names)
                if isinstance(parsed, dict):
                    keys = sorted(int(k) for k in parsed)
                    if keys != list(range(len(keys))):
                        raise ValueError("non-contiguous class ids")
                    names = [str(parsed[k] if k in parsed else parsed[str(k)]) for k in keys]
                elif isinstance(parsed, (list, tuple)):
                    names = [str(name) for name in parsed]
                else:
                    raise ValueError("names is neither a dict nor a list")
            except (KeyError, SyntaxError, TypeError, ValueError) as exc:
                raise ValueError(f"invalid class metadata in vision model: {exc}") from exc
            expected_names = CARD_NAMES + (["seat", "button"] if len(names) == 54 else [])
            manifest_names = artifact.entry.get("classes")
            if (
                names != expected_names
                or names != manifest_names
                or (class_count is not None and len(names) != class_count)
            ):
                raise ValueError("incompatible class metadata in vision model")
        self._input = inputs[0].name
        self._artifact = artifact

    def recognize(
        self,
        img: Image.Image,
        ocr_numbers: bool = False,
        deep_stacks: bool = False,
        fail_fast_abstain_below: float | None = None,
    ) -> RecognizedState:
        rgb = np.asarray(img.convert("RGB"))
        H, W = rgb.shape[:2]
        canvas, ratio, dw, dh = _letterbox(rgb)
        blob = canvas.astype(np.float32).transpose(2, 0, 1)[None] / 255.0  # (1,3,640,640)
        out = self._session.run(None, {self._input: blob})[0]
        dets = _decode(np.asarray(out), ratio, dw, dh, _CONF, _IOU, image_size=(W, H))
        button_candidates: list[tuple[float, float, float]] = []
        hole: list[CardCandidate] = []
        board: list[CardCandidate] = []
        seats: list[Point] = []
        for c, cf, x1, y1, x2, y2 in dets:
            cxp, cyp = (x1 + x2) / 2, (y1 + y2) / 2
            if c < 52:
                box = (int(x1), int(y1), int(x2 - x1), int(y2 - y1))
                (hole if cyp > H * 0.66 else board).append((cxp, cyp, cf, CARD_NAMES[c], box))
            elif c == SEAT_CLS:
                seats.append((cxp, cyp))
            elif c == BUTTON_CLS:
                button_candidates.append((cf, cxp, cyp))
        # corte top-k pela CONFIANÇA (não pela posição), depois ordena L->R por x
        hole_top = sorted(hole, key=lambda item: item[2], reverse=True)[:2]
        board_top = sorted(board, key=lambda item: item[2], reverse=True)[:5]
        hole_ordered = sorted(hole_top, key=lambda item: item[0])
        board_ordered = sorted(board_top, key=lambda item: item[0])
        hole_sorted = [name for _, _, _, name, _ in hole_ordered]
        board_sorted = [name for _, _, _, name, _ in board_ordered]
        card_confs = [float(cf) for _, _, cf, _, _ in hole_ordered] + [
            float(cf) for _, _, cf, _, _ in board_ordered
        ]
        card_boxes = [item[4] for item in (*hole_ordered, *board_ordered)]

        button = _select_button(button_candidates, (W, H))
        if len(seats) >= 2 and hole_top:
            hero = (
                float(np.mean([item[0] for item in hole_top])),
                float(np.mean([item[1] for item in hole_top])),
            )
            n_players, position = derive_position(seats, hero, button)
        else:
            n_players, position = len(seats), ""

        if ocr_numbers and _cards_force_abstention(
            hole_sorted, board_sorted, card_confs, fail_fast_abstain_below
        ):
            pot, potc, stacks, stack_confs, src = None, 0.0, None, None, "skipped-card-gate"
        else:
            pot, potc, stacks, stack_confs, src = _read_numbers(
                rgb, _gray(img), card_boxes, seats, ocr_numbers, deep_stacks
            )
        confs = list(card_confs)
        if pot is not None:
            confs.append(potc)
        return RecognizedState(
            hole=hole_sorted,
            board=board_sorted,
            pot=pot,
            n_cards=len(hole_sorted) + len(board_sorted),
            confidence=round(float(np.mean(confs)) if confs else 0.0, 3),
            card_confidences=card_confs,
            pot_confidence=float(potc) if pot is not None else None,
            n_players=n_players,
            position=position,
            stacks=stacks,
            stack_confidences=stack_confs,
            pot_source=src,
        )


_recognizer_lock = threading.Lock()


@lru_cache(maxsize=2)
def _cached_recognizer_impl(artifact: VerifiedModelArtifact) -> OnnxRecognizer:
    return OnnxRecognizer(
        artifact.path,
        manifest_path=artifact.manifest_path,
        artifact=artifact,
    )


def _cached_recognizer(artifact: VerifiedModelArtifact) -> OnnxRecognizer:
    """Sessão ONNX cacheada por recibo criptográfico. O lock serializa a 1ª construção pra que
    o warmup no boot e uma requisição concorrente NÃO carreguem a sessão em duplicata (a que
    chegar durante a carga espera a MESMA sessão, em vez de refazer o cold-start)."""
    with _recognizer_lock:
        return _cached_recognizer_impl(artifact)


def recognize_table_onnx(
    img: Image.Image,
    ocr_numbers: bool = False,
    deep_stacks: bool = False,
    fail_fast_abstain_below: float | None = None,
) -> RecognizedState:
    """Reconhece com o modelo TREINADO (F2). Requer o .onnx em models/ (ou POKER_VISION_MODEL).
    A sessão é cacheada pelo hash do artefato e do manifesto; revogação é revalidada a cada uso."""
    artifact = _resolve_vision_artifact()
    rec = _cached_recognizer(artifact)
    return rec.recognize(
        img,
        ocr_numbers=ocr_numbers,
        deep_stacks=deep_stacks,
        fail_fast_abstain_below=fail_fast_abstain_below,
    )
