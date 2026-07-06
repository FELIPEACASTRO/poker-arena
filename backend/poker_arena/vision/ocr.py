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
import threading
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

Number = tuple[int, float, float, float]  # (valor, cx, cy, confiança) em pixels

_engine_lock = threading.Lock()


@lru_cache(maxsize=1)
def _engine_cached():
    try:
        from rapidocr_onnxruntime import RapidOCR
    except Exception:
        return None
    return RapidOCR()


def _engine():
    """Carrega o RapidOCR uma vez (singleton). Retorna None se a lib não está instalada.

    O lock serializa a 1ª construção: se o warmup no boot e uma requisição concorrente
    competem, um ESPERA o outro em vez de os dois carregarem o engine em duplicata
    (o `lru_cache` do CPython não serializa misses concorrentes da mesma chave)."""
    with _engine_lock:
        return _engine_cached()


def available() -> bool:
    return _engine() is not None


_MAX_OCR_W = 900  # teto de largura do passe global de OCR — a detecção do RapidOCR escala
# com a resolução; telas grandes (1300px+) estouram o orçamento de 4s. O pote (texto grande)
# sobrevive ao downscale; os stacks pequenos são relidos por ROI ampliada depois.


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
        small = np.asarray(Image.fromarray(rgb).resize((round(W * scale), round(H * scale)),
                                                       Image.BILINEAR))
    else:
        small = rgb
    result, _ = eng(small)
    inv = 1.0 / scale
    out: list[Number] = []
    for box, txt, conf in result or []:
        if conf < min_conf:
            continue
        digits = re.sub(r"[^0-9]", "", txt)
        if not digits or len(digits) > 9:  # ignora vazio / lixo gigante
            continue
        cx = float(np.mean([p[0] for p in box])) * inv  # coords de volta ao ORIGINAL
        cy = float(np.mean([p[1] for p in box])) * inv
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
    deep_stacks: bool = False,
    max_roi: int = 6,
) -> ScreenNumbers:
    """Lê os números da tela (pote [+ stacks]).

    `deep_stacks=False` (padrão, caminho de BAIXA LATÊNCIA <=4s): OCR só a faixa central do
    POTE (recorte pequeno + upscale) — latência LIMITADA e previsível, independente de quanto
    texto a tela tem; stacks não são críticos p/ decisão. `deep_stacks=True` (benchmark de
    acurácia): passe global na imagem + releitura por assento (stacks), com teto `max_roi`."""
    if not deep_stacks:  # caminho RÁPIDO (<=4s): recorta a faixa do pote (acima do board),
        # 1 passe de OCR (poucos boxes -> tempo bounded); pega o número mais central.
        x0, x1 = int(0.24 * W), int(0.76 * W)
        y0, y1 = int(0.10 * H), int(0.40 * H)
        crop = rgb[y0:y1, x0:x1]
        nums = read_numbers(crop)  # já faz downscale se o recorte for grande
        if nums:
            cw, ch = x1 - x0, y1 - y0
            val, _cx, _cy, conf = min(
                nums, key=lambda n: (n[1] - cw / 2) ** 2 + (n[2] - ch / 2) ** 2)
            return ScreenNumbers(pot=val, pot_conf=conf, stacks=None)
        return ScreenNumbers(pot=None, pot_conf=0.0, stacks=None)

    sn = interpret(read_numbers(rgb), W, H, list(card_boxes), list(seat_centers))
    stacks = dict(sn.stacks or {})
    done = 0
    for si, (sx, sy) in enumerate(seat_centers):  # stack faltando -> relê ampliado
        if si in stacks or done >= max_roi:
            continue
        hit = read_roi(rgb, sx, sy + 0.035 * H, 0.085 * W, 0.075 * H)
        done += 1
        if hit is not None:
            stacks[si] = hit[0]
    pot, pot_conf = sn.pot, sn.pot_conf
    if pot is None:
        hit = read_roi(rgb, W / 2, H * 0.28, 0.18 * W, 0.14 * H)
        if hit is not None:
            pot, pot_conf = hit
    return ScreenNumbers(pot=pot, pot_conf=pot_conf, stacks=stacks or None)
