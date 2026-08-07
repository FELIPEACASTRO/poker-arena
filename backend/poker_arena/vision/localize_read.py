"""F4 estágio LER: dado o box de uma carta, recorta, faz upscale e propõe rank+naipe.

A doutrina medida (ver [[vision-f4-localize-read]]): o agnosticismo mora no LOCALIZADOR
(achar o retângulo-carta); ler um vocabulário fechado ainda depende de fonte, resolução,
oclusão e calibração. Upscale LANCZOS não cria detalhes ausentes.

O READER tem dois níveis, com AUSÊNCIA GRACIOSA:
  1. CNN (models/card_reader.onnx) — usado somente com manifesto, hash, governança e contrato
     aprovados. Quando aprovado, é preferido ao ZNCC.
  2. Fallback ZNCC (recognize._read_card) — sem o CNN, cai no reader por template no
     estilo sintético calibrado. O fallback mantém o diagnóstico, não prova equivalência.

Saída idêntica ao resto da visão: (nome_da_carta, confiança). O sanity/abstain não muda.
"""

from __future__ import annotations

import math
import os
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

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
from .recognize import _read_card

if TYPE_CHECKING:
    import onnxruntime as ort

# ORDEM das classes — TEM que bater com o notebook de treino (11_card_reader_cnn).
RANKS_R = "23456789TJQKA"  # rank: 13 classes (índice 0..12)
SUITS_R = "shdc"  # naipe: 4 classes (índice 0..3)
_CANON = (64, 96)  # (W, H) canônico de entrada do CNN — igual ao treino


def card_reader_path() -> Path:
    """Onde o CNN reader é procurado. Override por POKER_CARD_READER."""
    env = os.environ.get("POKER_CARD_READER")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "models" / "card_reader.onnx"


def card_reader_manifest_path() -> Path:
    """Manifesto obrigatório do reader CNN."""
    return model_manifest_path(card_reader_path(), "POKER_CARD_READER_MANIFEST")


def card_reader_available() -> bool:
    return model_artifact_available(
        card_reader_path(), "card_reader", manifest_path=card_reader_manifest_path()
    )


@lru_cache(maxsize=1)
def _reader_session(artifact: VerifiedModelArtifact) -> ort.InferenceSession:
    import onnxruntime as ort  # import tardio: só quando o CNN é usado

    if artifact.kind != "card_reader" or artifact.usage != "deployment":
        raise ModelArtifactUnavailable(
            "receipt_mismatch", "card reader received a receipt for another artifact"
        )
    revalidate_model_artifact_identity(artifact)
    try:
        session = ort.InferenceSession(str(artifact.path), providers=["CPUExecutionProvider"])
    except Exception as exc:  # noqa: BLE001 - normalize runtime load as gate rejection
        raise ModelArtifactUnavailable("runtime_load_failed", str(exc)) from exc
    revalidate_model_artifact_identity(artifact)
    verify_runtime_contract(artifact, session.get_inputs(), session.get_outputs())
    return session


def _softmax_max(logits: np.ndarray) -> float:
    e = np.exp(logits - logits.max())
    return float((e / e.sum()).max())


def _preprocess(crop_rgb: np.ndarray) -> np.ndarray:
    """Crop -> (1,3,H,W) normalizado [-1,1]. Igual ao pré-processo do treino."""
    im = Image.fromarray(crop_rgb).convert("RGB").resize(_CANON, Image.Resampling.BILINEAR)  # (W,H)
    arr = (np.asarray(im, dtype=np.float32) / 255.0 - 0.5) / 0.5  # HWC em [-1,1]
    return arr.transpose(2, 0, 1)[None]  # (1,3,96,64)


def _cnn_read(crop_rgb: np.ndarray) -> tuple[str, float]:
    """Lê a carta com o CNN treinado. Saídas esperadas: 'rank'(1,13) e 'suit'(1,4)
    (ou dois tensores nessa ordem). Confiança = min(softmax_max_rank, softmax_max_suit)."""
    p = card_reader_path()
    artifact = verify_model_artifact(p, "card_reader", manifest_path=card_reader_manifest_path())
    sess = _reader_session(artifact)
    outs = sess.run(None, {sess.get_inputs()[0].name: _preprocess(crop_rgb)})
    rank_logits, suit_logits = np.asarray(outs[0])[0], np.asarray(outs[1])[0]
    ri, si = int(rank_logits.argmax()), int(suit_logits.argmax())
    conf = min(_softmax_max(rank_logits), _softmax_max(suit_logits))
    return RANKS_R[ri] + SUITS_R[si], round(conf, 3)


def read_card(
    rgb: np.ndarray, box: tuple[int, int, int, int], upscale: float = 3.0, use_cnn: bool = True
) -> tuple[str, float]:
    """Lê UMA carta: recorta o box, faz upscale LANCZOS e lê. Usa o CNN se instalado
    (lê a fonte real), senão cai no reader ZNCC (template sintético). `upscale` fabrica a
    resolução que o localizador não garante."""
    if isinstance(upscale, bool) or not isinstance(upscale, int | float):
        raise TypeError("upscale must be a finite number")
    upscale = float(upscale)
    if not math.isfinite(upscale) or not 0.25 <= upscale <= 8.0:
        raise ValueError("upscale must be finite and between 0.25 and 8.0")
    raw_x, raw_y, w, h = (int(box[0]), int(box[1]), int(box[2]), int(box[3]))
    if w <= 0 or h <= 0 or rgb.ndim != 3:
        return "", 0.0
    image_h, image_w = rgb.shape[:2]
    x0, y0 = max(0, raw_x), max(0, raw_y)
    x1, y1 = min(image_w, raw_x + w), min(image_h, raw_y + h)
    crop = rgb[y0:y1, x0:x1]
    if crop.shape[0] < 6 or crop.shape[1] < 6:
        return "", 0.0
    if upscale and upscale != 1.0:
        im = Image.fromarray(crop)
        nw, nh = int(im.width * upscale), int(im.height * upscale)
        crop = np.asarray(im.resize((nw, nh), Image.Resampling.LANCZOS))
    if use_cnn and card_reader_available():
        return _cnn_read(crop)
    ch, cw = crop.shape[:2]
    return _read_card(crop, (0, 0, cw, ch))


def read_cards(
    rgb: np.ndarray,
    boxes: Sequence[tuple[int, int, int, int]],
    upscale: float = 3.0,
    use_cnn: bool = True,
) -> list[tuple[str, float]]:
    """Lê todas as cartas dadas as caixas do localizador. Ordem preservada."""
    return [read_card(rgb, b, upscale, use_cnn) for b in boxes]
