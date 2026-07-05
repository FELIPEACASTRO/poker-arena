"""Leitura de NÚMEROS da tela (pote + stacks + apostas) por OCR — o elo forte.

Os números eram o elo fraco (template de dígitos, ~40-90%). Aqui usamos o RapidOCR
(modelos PP-OCR rodando em onnxruntime — o MESMO runtime das cartas, sem arrastar
PyTorch/Paddle), que lê dígitos de fundo variado a ~100%. UM passe de OCR extrai TODOS
os números da tela; a geometria depois separa POTE (central) de STACK (junto ao assento).

Ausência graciosa: se o rapidocr não estiver instalado, `available()` é False e o
reconhecedor cai no leitor por template. Carrega o modelo UMA vez (singleton).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

Number = tuple[int, float, float, float]  # (valor, cx, cy, confiança) em pixels


@lru_cache(maxsize=1)
def _engine():
    """Carrega o RapidOCR uma vez. Retorna None se a lib não está instalada."""
    try:
        from rapidocr_onnxruntime import RapidOCR
    except Exception:
        return None
    return RapidOCR()


def available() -> bool:
    return _engine() is not None


def read_numbers(rgb: np.ndarray, min_conf: float = 0.5) -> list[Number]:
    """Todos os números inteiros lidos na imagem: (valor, cx, cy, confiança)."""
    eng = _engine()
    if eng is None:
        return []
    result, _ = eng(rgb)
    out: list[Number] = []
    for box, txt, conf in result or []:
        if conf < min_conf:
            continue
        digits = re.sub(r"[^0-9]", "", txt)
        if not digits or len(digits) > 9:  # ignora vazio / lixo gigante
            continue
        cx = float(np.mean([p[0] for p in box]))
        cy = float(np.mean([p[1] for p in box]))
        out.append((int(digits), cx, cy, float(conf)))
    return out


def read_roi(rgb: np.ndarray, cx: float, cy: float, hw: float, hh: float,
             scale: float = 3.0) -> tuple[int, float] | None:
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
    big = im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS)
    result, _ = eng(np.asarray(big))
    best = None
    for _box, txt, conf in result or []:
        digits = re.sub(r"[^0-9]", "", txt)
        if digits and 0 < len(digits) <= 9 and (best is None or conf > best[1]):
            best = (int(digits), float(conf))
    return best


def _inside_any(cx: float, cy: float, boxes: list[tuple[int, int, int, int]]) -> bool:
    """O ponto cai dentro de alguma caixa de carta? (número = índice da carta, ignorar)."""
    return any(x <= cx <= x + w and y <= cy <= y + h for x, y, w, h in boxes)


@dataclass
class ScreenNumbers:
    """Números interpretados da tela."""

    pot: int | None = None
    pot_conf: float = 0.0
    stacks: dict[int, int] | None = None  # índice do assento -> fichas lidas


def interpret(
    numbers: list[Number],
    W: int,
    H: int,
    card_boxes: list[tuple[int, int, int, int]] = (),
    seat_centers: list[tuple[float, float]] = (),
) -> ScreenNumbers:
    """Separa POTE (número central, fora de carta e longe de assento) dos STACKS
    (número mais próximo de cada assento). Geometria pura sobre o que o OCR leu."""
    # descarta números que são índice de carta (caem dentro de uma carta)
    nums = [n for n in numbers if not _inside_any(n[1], n[2], list(card_boxes))]

    # STACK de cada assento = número mais próximo dele (dentro de um raio razoável)
    stacks: dict[int, int] = {}
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
            used.add(best)

    # POTE = número central que sobrou (perto do centro horizontal, banda superior-central)
    cx0 = W / 2
    pot, pot_conf, best = None, 0.0, None
    bestscore = 1e18
    for i, (_val, cx, cy, _conf) in enumerate(nums):
        if i in used:
            continue
        if not (0.30 * W <= cx <= 0.70 * W and 0.12 * H <= cy <= 0.58 * H):
            continue
        score = (cx - cx0) ** 2 + (cy - H * 0.33) ** 2  # mais perto do centro-pote = melhor
        if score < bestscore:
            bestscore, best = score, i
    if best is not None:
        pot, _, _, pot_conf = nums[best]
    return ScreenNumbers(pot=pot, pot_conf=pot_conf, stacks=stacks or None)


def read_screen(
    rgb: np.ndarray,
    W: int,
    H: int,
    card_boxes: list[tuple[int, int, int, int]] = (),
    seat_centers: list[tuple[float, float]] = (),
) -> ScreenNumbers:
    """Leitura COMPLETA dos números: um passe global + RELEITURA por ROI (upscale) do
    que faltou. Empurra pote/stacks pro teto sem custo quando o passe já resolveu."""
    sn = interpret(read_numbers(rgb), W, H, list(card_boxes), list(seat_centers))
    stacks = dict(sn.stacks or {})
    for si, (sx, sy) in enumerate(seat_centers):  # stack faltando -> relê o assento ampliado
        if si in stacks:
            continue
        hit = read_roi(rgb, sx, sy + 0.035 * H, 0.085 * W, 0.075 * H)
        if hit is not None:
            stacks[si] = hit[0]
    # POTE: o passe global (que exclui cartas e escolhe o número central) é o melhor
    # seletor; a ROI ampliada só entra como fallback quando o passe não achou pote.
    pot, pot_conf = sn.pot, sn.pot_conf
    if pot is None:
        hit = read_roi(rgb, W / 2, H * 0.28, 0.18 * W, 0.14 * H)
        if hit is not None:
            pot, pot_conf = hit
    return ScreenNumbers(pot=pot, pot_conf=pot_conf, stacks=stacks or None)
