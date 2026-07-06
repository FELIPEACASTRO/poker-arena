"""F4 estágio LER: dado o box de uma carta (de QUALQUER localizador), recorta, faz
upscale e lê rank+suit — a parte trivial.

A doutrina medida (ver [[vision-f4-localize-read]]): o agnosticismo mora no LOCALIZADOR
(achar o retângulo-carta em qualquer UI); depois que a carta está isolada, LER um
vocabulário FECHADO de 52 é fácil. O fracasso do VLM foi RESOLUÇÃO (carta ~30px numa tela
reduzida) — então aqui FABRICAMOS resolução com upscale LANCZOS antes de ler.

O READER tem dois níveis, com AUSÊNCIA GRACIOSA:
  1. CNN (models/card_reader.onnx) — treinado em fontes/estilos DIVERSOS (notebook 11), lê a
     fonte REAL do cliente (o ZNCC sintético falhava nela: medido 0/6 no 247). Preferido.
  2. Fallback ZNCC (recognize._read_card) — sem o CNN, cai no reader por template (100% no
     estilo sintético calibrado). Assim o pipeline nunca quebra por falta do modelo.

Saída idêntica ao resto da visão: (nome_da_carta, confiança). O sanity/abstain não muda.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from .recognize import _read_card

# ORDEM das classes — TEM que bater com o notebook de treino (11_card_reader_cnn).
RANKS_R = "23456789TJQKA"  # rank: 13 classes (índice 0..12)
SUITS_R = "shdc"           # naipe: 4 classes (índice 0..3)
_CANON = (64, 96)          # (W, H) canônico de entrada do CNN — igual ao treino


def card_reader_path() -> Path:
    """Onde o CNN reader é procurado. Override por POKER_CARD_READER."""
    env = os.environ.get("POKER_CARD_READER")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "models" / "card_reader.onnx"


def card_reader_available() -> bool:
    return card_reader_path().exists()


@lru_cache(maxsize=1)
def _reader_session(path: str, mtime: float):
    import onnxruntime as ort  # import tardio: só quando o CNN é usado

    return ort.InferenceSession(path, providers=["CPUExecutionProvider"])


def _softmax_max(logits: np.ndarray) -> float:
    e = np.exp(logits - logits.max())
    return float((e / e.sum()).max())


def _preprocess(crop_rgb: np.ndarray) -> np.ndarray:
    """Crop -> (1,3,H,W) normalizado [-1,1]. Igual ao pré-processo do treino."""
    im = Image.fromarray(crop_rgb).convert("RGB").resize(_CANON, Image.BILINEAR)  # (W,H)
    arr = (np.asarray(im, dtype=np.float32) / 255.0 - 0.5) / 0.5  # HWC em [-1,1]
    return arr.transpose(2, 0, 1)[None]  # (1,3,96,64)


def _cnn_read(crop_rgb: np.ndarray) -> tuple[str, float]:
    """Lê a carta com o CNN treinado. Saídas esperadas: 'rank'(1,13) e 'suit'(1,4)
    (ou dois tensores nessa ordem). Confiança = min(softmax_max_rank, softmax_max_suit)."""
    p = card_reader_path()
    sess = _reader_session(str(p), p.stat().st_mtime)
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
    x, y, w, h = int(box[0]), int(box[1]), int(box[2]), int(box[3])
    x, y = max(0, x), max(0, y)
    crop = rgb[y : y + h, x : x + w]
    if crop.shape[0] < 6 or crop.shape[1] < 6:
        return "", 0.0
    if upscale and upscale != 1.0:
        im = Image.fromarray(crop)
        nw, nh = int(im.width * upscale), int(im.height * upscale)
        crop = np.asarray(im.resize((nw, nh), Image.LANCZOS))
    if use_cnn and card_reader_available():
        try:
            return _cnn_read(crop)
        except Exception:  # noqa: BLE001 — CNN inválido/incompatível -> cai no ZNCC
            pass
    ch, cw = crop.shape[:2]
    return _read_card(crop, (0, 0, cw, ch))


def read_cards(
    rgb: np.ndarray,
    boxes: list[tuple[int, int, int, int]],
    upscale: float = 3.0,
    use_cnn: bool = True,
) -> list[tuple[str, float]]:
    """Lê todas as cartas dadas as caixas do localizador. Ordem preservada."""
    return [read_card(rgb, b, upscale, use_cnn) for b in boxes]
