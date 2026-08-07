"""Leitura de NÚMEROS da tela (pote + stacks + apostas) por OCR — o elo forte.

Os números eram um elo fraco. Aqui usamos RapidOCR (PP-OCR em onnxruntime) para propor
valores e a geometria separa POTE de STACK. Texto OCR ambíguo é rejeitado; pontuação
jamais é apagada cegamente. Não há alegação de acurácia universal sem benchmark real
rotulado por cliente/tela.

Ausência graciosa: se o rapidocr não estiver instalado, `available()` é False e o
reconhecedor cai no leitor por template. Carrega o modelo UMA vez (singleton).
"""

from __future__ import annotations

import math
import re
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import lru_cache

import numpy as np

Number = tuple[int, float, float, float]  # (valor, cx, cy, confiança) em pixels

_engine_lock = threading.Lock()
_inference_lock = threading.Lock()


class OCREngineInitializationError(RuntimeError):
    """RapidOCR is installed but its import or model initialization is broken."""


@lru_cache(maxsize=1)
def _engine_cached():
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ModuleNotFoundError as exc:
        if exc.name == "rapidocr_onnxruntime":
            return None
        raise OCREngineInitializationError("RapidOCR dependency import failed") from exc
    except ImportError as exc:
        raise OCREngineInitializationError("RapidOCR import failed") from exc
    try:
        return RapidOCR()
    except Exception as exc:  # noqa: BLE001 - normalize third-party initialization failures
        raise OCREngineInitializationError("RapidOCR model initialization failed") from exc


def _engine():
    """Carrega o RapidOCR uma vez (singleton). Retorna None se a lib não está instalada.

    O lock serializa a 1ª construção: se o warmup no boot e uma requisição concorrente
    competem, um ESPERA o outro em vez de os dois carregarem o engine em duplicata
    (o `lru_cache` do CPython não serializa misses concorrentes da mesma chave)."""
    with _engine_lock:
        return _engine_cached()


def available() -> bool:
    return _engine() is not None


_MAX_OCR_W = 900  # teto de largura para limitar custo do passe global
# O downscale é uma otimização; latência e preservação do texto precisam ser medidas no
# hardware e corpus alvo. Stacks pequenos podem ser relidos por ROI no caminho profundo.


_LABEL = r"(?:(?:pot|stack|bet|chips?)\s*[:=]?\s*)?"
_CURRENCY = r"[$€£]?\s*"
_TRAILING_UNIT = r"\s*(?:chips?|bb)?"


def _parse_amount(raw: object) -> int | None:
    """Normalize an unambiguous integer chip amount, otherwise fail closed.

    Thousands separators and explicit K/M suffixes are supported. Unsuffixed decimals
    (for example ``$10.50``) are rejected because silently deleting punctuation changes
    the amount by orders of magnitude.
    """
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if 0 <= raw <= 999_999_999 else None
    if isinstance(raw, float):
        return (
            int(raw)
            if math.isfinite(raw) and 0 <= raw <= 999_999_999 and raw.is_integer()
            else None
        )
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if not value or "-" in value:
        return None

    suffix = re.fullmatch(
        _LABEL + _CURRENCY + r"(\d+(?:[.,]\d+)?)\s*([kKmM])" + _TRAILING_UNIT,
        value,
        flags=re.IGNORECASE,
    )
    if suffix:
        number, unit = suffix.groups()
        try:
            scaled = Decimal(number.replace(",", ".")) * (
                Decimal(1_000) if unit.lower() == "k" else Decimal(1_000_000)
            )
        except InvalidOperation:
            return None
        if scaled != scaled.to_integral_value():
            return None
        amount = int(scaled)
        return amount if 0 <= amount <= 999_999_999 else None

    integer = re.fullmatch(
        _LABEL + _CURRENCY + r"(\d+|\d{1,3}(?:[,\s]\d{3})+)" + _TRAILING_UNIT,
        value,
        flags=re.IGNORECASE,
    )
    if not integer:
        return None
    amount = int(re.sub(r"[,\s]", "", integer.group(1)))
    return amount if amount <= 999_999_999 else None


def read_numbers(rgb: np.ndarray, min_conf: float = 0.5) -> list[Number]:
    """Todos os números inteiros lidos na imagem: (valor, cx, cy, confiança). Faz DOWNSCALE
    de telas grandes antes do OCR (latência) e reescala as coordenadas de volta ao original."""
    eng = _engine()
    if eng is None:
        return []
    H, W = rgb.shape[:2]
    scale = min(1.0, _MAX_OCR_W / W)  # <1 só quando a imagem é maior que o teto
    if scale < 1.0:
        from PIL import Image

        small = np.asarray(
            Image.fromarray(rgb).resize(
                (round(W * scale), round(H * scale)), Image.Resampling.BILINEAR
            )
        )
    else:
        small = rgb
    # RapidOCR owns mutable runtime/session state.  The singleton is shared by all
    # thread-pool requests, therefore inference itself must be serialized as well as
    # first construction.  This trades peak throughput for deterministic safety.
    with _inference_lock:
        result, _ = eng(small)
    inv = 1.0 / scale
    out: list[Number] = []
    for box, txt, conf in result or []:
        if conf < min_conf:
            continue
        amount = _parse_amount(txt)
        if amount is None:
            continue
        cx = float(np.mean([p[0] for p in box])) * inv  # coords de volta ao ORIGINAL
        cy = float(np.mean([p[1] for p in box])) * inv
        out.append((amount, cx, cy, float(conf)))
    return out


def read_roi(
    rgb: np.ndarray,
    cx: float,
    cy: float,
    hw: float,
    hh: float,
    scale: float = 3.0,
    min_conf: float = 0.5,
) -> tuple[int, float] | None:
    """Lê UM número num recorte pequeno, com UPSCALE (números de HUD pequenos ficam
    legíveis). Devolve (valor, confiança) do número mais confiante, ou None."""
    from PIL import Image

    eng = _engine()
    if eng is None:
        return None
    H, W = rgb.shape[:2]
    x0, y0 = max(0, int(cx - hw)), max(0, int(cy - hh))
    x1, y1 = min(W, int(cx + hw)), min(H, int(cy + hh))
    if x1 - x0 < 6 or y1 - y0 < 6:
        return None
    crop = rgb[y0:y1, x0:x1]
    im = Image.fromarray(crop)
    big = im.resize((int(im.width * scale), int(im.height * scale)), Image.Resampling.LANCZOS)
    with _inference_lock:
        result, _ = eng(np.asarray(big))
    best = None
    for _box, txt, conf in result or []:
        amount = _parse_amount(txt)
        if amount is not None and conf >= min_conf and (best is None or conf > best[1]):
            best = (amount, float(conf))
    return best


def _inside_any(cx: float, cy: float, boxes: Sequence[tuple[int, int, int, int]]) -> bool:
    """O ponto cai dentro de alguma caixa de carta? (número = índice da carta, ignorar)."""
    return any(x <= cx <= x + w and y <= cy <= y + h for x, y, w, h in boxes)


@dataclass
class ScreenNumbers:
    """Números interpretados da tela."""

    pot: int | None = None
    pot_conf: float = 0.0
    stacks: dict[int, int] | None = None  # índice do assento -> fichas lidas
    stack_confidences: dict[int, float] | None = None


def interpret(
    numbers: list[Number],
    W: int,
    H: int,
    card_boxes: Sequence[tuple[int, int, int, int]] = (),
    seat_centers: Sequence[tuple[float, float]] = (),
) -> ScreenNumbers:
    """Separa POTE (número central, fora de carta e longe de assento) dos STACKS
    (número mais próximo de cada assento). Geometria pura sobre o que o OCR leu."""
    # descarta números que são índice de carta (caem dentro de uma carta)
    nums = [n for n in numbers if not _inside_any(n[1], n[2], list(card_boxes))]

    # STACK de cada assento = número mais próximo dele (dentro de um raio razoável)
    stacks: dict[int, int] = {}
    stack_confidences: dict[int, float] = {}
    used: set[int] = set()
    radius2 = (0.12 * W) ** 2 + (0.12 * H) ** 2
    for si, (sx, sy) in enumerate(seat_centers):
        best, bd = None, radius2
        for i, (_val, cx, cy, _c) in enumerate(nums):
            if i in used:
                continue
            d = (cx - sx) ** 2 + (cy - sy) ** 2
            if d < bd:
                bd, best = d, i
        if best is not None:
            stacks[si] = nums[best][0]
            stack_confidences[si] = nums[best][3]
            used.add(best)

    # POTE = número central que sobrou (perto do centro horizontal, banda superior-central)
    pot, pot_conf = None, 0.0
    candidates: list[int] = []
    for i, (_val, cx, cy, _conf) in enumerate(nums):
        if i in used:
            continue
        if not (0.30 * W <= cx <= 0.70 * W and 0.12 * H <= cy <= 0.58 * H):
            continue
        candidates.append(i)
    # Sem rótulo semântico, dois valores centrais são ambíguos (pote/aposta/HUD).
    # Abstém em vez de transformar proximidade geométrica em certeza semântica.
    if len(candidates) == 1:
        pot, _, _, pot_conf = nums[candidates[0]]
    return ScreenNumbers(
        pot=pot,
        pot_conf=pot_conf,
        stacks=stacks or None,
        stack_confidences=stack_confidences or None,
    )


def read_screen(
    rgb: np.ndarray,
    W: int,
    H: int,
    card_boxes: Sequence[tuple[int, int, int, int]] = (),
    seat_centers: Sequence[tuple[float, float]] = (),
    deep_stacks: bool = False,
    max_roi: int = 6,
) -> ScreenNumbers:
    """Lê os números da tela (pote [+ stacks]).

    `deep_stacks=False` (padrão) restringe o OCR à faixa central do pote para reduzir
    custo; não garante um teto de latência. `deep_stacks=True` faz passe global e releitura
    por assento, com teto `max_roi`, e é destinado a avaliação offline."""
    if not deep_stacks:  # caminho de menor custo: recorta a faixa do pote
        # Um passe de OCR; a interpretação ainda exclui cartas/assentos e ambiguidade.
        x0, x1 = int(0.24 * W), int(0.76 * W)
        y0, y1 = int(0.10 * H), int(0.40 * H)
        crop = rgb[y0:y1, x0:x1]
        nums = [
            (value, cx + x0, cy + y0, confidence)
            for value, cx, cy, confidence in read_numbers(crop)
        ]
        if nums:
            interpreted = interpret(nums, W, H, card_boxes, seat_centers)
            return ScreenNumbers(pot=interpreted.pot, pot_conf=interpreted.pot_conf)
        return ScreenNumbers(pot=None, pot_conf=0.0, stacks=None)

    sn = interpret(read_numbers(rgb), W, H, list(card_boxes), list(seat_centers))
    stacks = dict(sn.stacks or {})
    stack_confidences = dict(sn.stack_confidences or {})
    done = 0
    for si, (sx, sy) in enumerate(seat_centers):  # stack faltando -> relê ampliado
        if si in stacks or done >= max_roi:
            continue
        hit = read_roi(rgb, sx, sy + 0.035 * H, 0.085 * W, 0.075 * H)
        done += 1
        if hit is not None:
            stacks[si] = hit[0]
            stack_confidences[si] = hit[1]
    pot, pot_conf = sn.pot, sn.pot_conf
    if pot is None:
        hit = read_roi(rgb, W / 2, H * 0.28, 0.18 * W, 0.14 * H)
        if hit is not None:
            pot, pot_conf = hit
    return ScreenNumbers(
        pot=pot,
        pot_conf=pot_conf,
        stacks=stacks or None,
        stack_confidences=stack_confidences or None,
    )
