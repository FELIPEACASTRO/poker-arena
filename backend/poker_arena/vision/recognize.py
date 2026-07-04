"""Reconhecedor F1 (baseline): imagem 2D -> estado, por template + cor.

MODULAR: (1) LOCALIZA cartas (segmentação por brilho), (2) LÊ rank+naipe de cada uma
(template + cor do naipe), (3) separa herói/board por posição, (4) lê o pote (dígitos
por template). É o baseline offline pra provar o pipeline e MEDIR acurácia — inclusive
a queda em estilos não vistos. O modelo AGNÓSTICO (treinado) é a F2, no notebook.

Nada de deep learning aqui de propósito: prova que a cadeia imagem->estado->decisão
funciona e dá a régua (held-out) que justifica treinar o detector agnóstico.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .seats import derive_position
from .synth import _RANK_DISP, _SUIT_SYM, CANONICAL, RANKS, SUITS, Style, _font

_TH = 150  # brilho acima disso = interior de carta (claro sobre feltro escuro)
_TEMPL = (34, 26)  # tamanho canônico de template (h, w)
_COLORS = {
    "black": (20, 20, 20), "red": (200, 30, 40), "blue": (30, 90, 210), "green": (20, 120, 40),
}
_SUIT_BY_COLOR = {"black": ("s", "c"), "red": ("h", "d"), "blue": ("d",), "green": ("c",)}


@dataclass
class RecognizedState:
    """O que a visão extraiu (antes do sanity-check)."""

    hole: list[str] = field(default_factory=list)
    board: list[str] = field(default_factory=list)
    pot: int | None = None
    n_cards: int = 0
    confidence: float = 1.0  # menor quando algo ficou ambíguo
    n_players: int = 0  # participantes na mesa (0 = não detectado)
    position: str = ""  # posição do herói (BTN/SB/BB/UTG/...) — "" se indefinida


def _gray(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("L"), dtype=np.uint8)


def _glyph(text: str, font: ImageFont.FreeTypeFont) -> np.ndarray:
    """Renderiza um glifo em preto sobre branco, recorta na tinta, normaliza (0..1, tinta=1)."""
    tmp = Image.new("L", (140, 140), 255)
    d = ImageDraw.Draw(tmp)
    d.text((10, 10), text, font=font, fill=0)
    a = 255 - np.asarray(tmp)  # tinta clara
    ys, xs = np.where(a > 40)
    if len(xs) == 0:
        return np.zeros(_TEMPL)
    crop = a[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    im = Image.fromarray(crop).resize((_TEMPL[1], _TEMPL[0]))
    arr = np.asarray(im, dtype=np.float32)
    return arr / (arr.max() or 1)


def _zncc(a: np.ndarray, b: np.ndarray) -> float:
    """Correlação cruzada normalizada (invariante a brilho/contraste)."""
    a = a - a.mean()
    b = b - b.mean()
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    return float((a * b).sum() / (na * nb)) if na and nb else 0.0


class _Templates:
    """Templates de rank, naipe e dígito tirados de UM estilo canônico (F1)."""

    def __init__(self, style: Style = CANONICAL) -> None:
        f_idx = _font(style.font, 48)
        self.ranks = {r: _glyph(_RANK_DISP.get(r, r), f_idx) for r in RANKS}
        self.suits = {s: _glyph(_SUIT_SYM[s], f_idx) for s in SUITS}
        self.digits = {str(d): _glyph(str(d), _font(style.font, 40)) for d in range(10)}


_T = _Templates()


def _components(mask: np.ndarray, min_area: int) -> list[tuple[int, int, int, int]]:
    """Componentes conexos (BFS) numa máscara reduzida -> caixas (x, y, w, h)."""
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    boxes = []
    for sy in range(h):
        for sx in range(w):
            if mask[sy, sx] and not seen[sy, sx]:
                q = deque([(sy, sx)])
                seen[sy, sx] = True
                x0 = x1 = sx
                y0 = y1 = sy
                area = 0
                while q:
                    cy, cx = q.popleft()
                    area += 1
                    x0, x1 = min(x0, cx), max(x1, cx)
                    y0, y1 = min(y0, cy), max(y1, cy)
                    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        ny, nx = cy + dy, cx + dx
                        if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                            seen[ny, nx] = True
                            q.append((ny, nx))
                if area >= min_area:
                    boxes.append((x0, y0, x1 - x0 + 1, y1 - y0 + 1))
    return boxes


def _find_cards(gray: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Localiza as cartas (regiões claras, proporção ~1.4). AGNÓSTICO A RESOLUÇÃO:
    o downscale e o tamanho mínimo de carta escalam com a largura da imagem, então
    funciona em qualquer monitor/tela (cada aluno tem uma)."""
    H, W = gray.shape
    scale = max(1, round(W / 300))  # processa em ~300px de largura, qualquer resolução
    small = np.asarray(Image.fromarray(gray).resize((max(1, W // scale), max(1, H // scale))))
    mask = small > _TH
    min_w = max(16.0, W * 0.025)  # carta >= 2.5% da largura da imagem
    boxes = _components(mask, min_area=int((min_w * min_w * 1.2) / (scale * scale)))
    out = []
    for x, y, w, h in boxes:
        X, Y, Wd, Hd = x * scale, y * scale, w * scale, h * scale
        ar = Hd / max(Wd, 1)
        if 1.15 <= ar <= 1.75 and Wd >= min_w and Hd >= min_w * 1.1:  # proporção de carta
            out.append((X, Y, Wd, Hd))
    return out


def _blob_centers(
    mask: np.ndarray, scale: int, min_area: int, max_dim: float, ar_lo: float, ar_hi: float
) -> list[tuple[float, float]]:
    """Centros (na resolução original) dos componentes ~redondos de uma máscara de cor.
    `max_dim` descarta blobs grandes demais (ex.: feltro azul virando um bloco só) —
    aí a leitura de assentos ABSTÉM (0 jogadores) em vez de contar errado."""
    out = []
    for x, y, w, h in _components(mask, min_area):
        ar = w / max(h, 1)
        if ar_lo <= ar <= ar_hi and w <= max_dim and h <= max_dim:
            out.append(((x + w / 2) * scale, (y + h / 2) * scale))
    return out


def _locate_seats(rgb: np.ndarray) -> tuple[list[tuple[float, float]], tuple[float, float] | None]:
    """Acha os avatares dos jogadores (discos AZULADOS) e o dealer button (disco
    DOURADO) por blob de cor. AGNÓSTICO A RESOLUÇÃO (escala pela largura). É o baseline
    F1 (estilo canônico); o detector treinado (F2) generaliza pra qualquer UI."""
    H, W = rgb.shape[:2]
    scale = max(1, round(W / 300))
    small = np.asarray(Image.fromarray(rgb).resize((max(1, W // scale), max(1, H // scale))))
    s16 = small.astype(np.int16)
    r, g, b = s16[..., 0], s16[..., 1], s16[..., 2]
    mx = small.max(2)
    seat_mask = (b > r + 12) & (b >= g) & (b > 90) & (mx < 205)  # disco azulado (não claro)
    btn_mask = (r > 180) & (g > 140) & (b < 130)  # disco dourado
    unit = (W * 0.03) / scale  # ~diâmetro do avatar na imagem reduzida
    seats = _blob_centers(seat_mask, scale, int(unit * unit * 0.35), unit * 2.6, 0.55, 1.8)
    btns = _blob_centers(btn_mask, scale, max(6, int(unit * unit * 0.10)), unit * 1.6, 0.5, 2.0)
    return seats, (btns[0] if btns else None)


def _color_class(rgb_crop: np.ndarray) -> str:
    """Classe de cor da tinta do naipe por SATURAÇÃO (robusto à borda cinza).

    Preto/cinza têm R≈G≈B (baixa saturação); vermelho/azul/verde têm um canal
    dominante. Ignora a borda acromática e decide a cor só sobre pixels saturados."""
    flat = rgb_crop.reshape(-1, 3).astype(np.float32)
    dark = flat[flat.min(1) < 170]  # tinta de QUALQUER cor (o fundo claro tem min alto)
    if len(dark) < 5:
        return "black"
    sat = dark.max(1) - dark.min(1)
    colored = dark[sat > 55]  # claramente colorido (não cinza/preto)
    if len(colored) < max(3, int(0.15 * len(dark))):
        return "black"  # maioria acromática -> naipe preto (♠/♣)
    r, g, b = np.median(colored, axis=0)
    if r >= g and r >= b:
        return "red"
    if b >= r and b >= g:
        return "blue"
    return "green"


def _top_bot(a: np.ndarray) -> float | None:
    """Razão tinta-topo / tinta-base do glifo (discrimina naipes da mesma cor)."""
    t = _tight(a, 120)
    if t is None or t.shape[0] < 4:
        return None
    hf = t.shape[0] // 2
    return float((t[:hf] > 120).sum()) / (float((t[hf:] > 120).sum()) or 1.0)


def _classify_suit(suit_gray: np.ndarray, color: str) -> str:
    """Naipe = cor (restringe) + top/bot ratio (decide ♠vs♣, ♥vs♦)."""
    if color == "blue":
        return "d"
    if color == "green":
        return "c"
    r = _top_bot(suit_gray)
    if color == "red":  # ♥ é top-heavy (~2.3), ♦ é baixo (~0.75)
        return "h" if (r is None or r > 1.3) else "d"
    return "s" if (r is None or r > 0.98) else "c"  # ♠(~1.12) vs ♣(~0.85)


def _tight(a: np.ndarray, th: float = 120) -> np.ndarray | None:
    """Recorta a matriz no bounding-box da tinta (a>th). th alto exclui a BORDA da
    carta (cinza ~170 -> invertido ~85), mantendo tinta de qualquer cor (>=165). None
    se vazia."""
    ys, xs = np.where(a > th)
    if len(xs) == 0:
        return None
    return a[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]


def _norm(a: np.ndarray) -> np.ndarray:
    """Recorta na tinta + redimensiona pro tamanho de template (comparável ao _glyph)."""
    t = _tight(a)
    if t is None:
        return np.zeros(_TEMPL, dtype=np.float32)
    im = Image.fromarray(np.clip(t, 0, 255).astype(np.uint8)).resize((_TEMPL[1], _TEMPL[0]))
    arr = np.asarray(im, dtype=np.float32)
    return arr / (arr.max() or 1)


def _read_card(rgb: np.ndarray, box: tuple[int, int, int, int]) -> tuple[str, float]:
    x, y, w, h = box
    card = rgb[y : y + h, x : x + w]
    # RE-APERTA na carta real (o box pode ter margem de feltro): pega o retângulo
    # claro (fundo da carta) — assim os recortes de índice ficam na posição certa,
    # e o comportamento de carta isolada (100%) transfere pro contexto da mesa.
    g0 = np.asarray(Image.fromarray(card).convert("L"))
    ys, xs = np.where(g0 > 150)
    if len(xs) > 20:
        card = card[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    gray = np.asarray(Image.fromarray(card).convert("L"), dtype=np.float32)
    # índice no canto superior-esquerdo: rank em cima, naipe logo abaixo (afastado
    # da borda pra não contaminar o recorte)
    ih = int(h * 0.30)
    rank_g = 255 - gray[int(h * 0.03) : int(h * 0.03) + ih, int(w * 0.06) : int(w * 0.55)]
    rq = _norm(rank_g)
    rank, rscore = max(((r, _zncc(rq, t)) for r, t in _T.ranks.items()), key=lambda kv: kv[1])
    # naipe: cor (do índice, confiável) restringe; a FORMA decide entre os da mesma cor
    # usando o naipe GRANDE do centro recortado LIMPO (y>0.52 já está abaixo do índice)
    cc = _color_class(card[int(h * 0.27) : int(h * 0.50), int(w * 0.05) : int(w * 0.42)])
    cands = _SUIT_BY_COLOR.get(cc, SUITS)
    if len(cands) == 1:
        return rank + cands[0], rscore
    big_g = 255 - gray[int(h * 0.52) : int(h * 0.94), int(w * 0.18) : int(w * 0.82)]
    sq = _norm(big_g)
    suit, sscore = max(((s, _zncc(sq, _T.suits[s])) for s in cands), key=lambda kv: kv[1])
    return rank + suit, min(rscore, sscore)


def _read_pot(rgb: np.ndarray, gray: np.ndarray) -> tuple[int | None, float]:
    """Lê o pote: região de texto claro na faixa central-superior (heurística F1)."""
    H, W = gray.shape
    band = gray[int(H * 0.18) : int(H * 0.42), int(W * 0.30) : int(W * 0.70)]
    mask = band > 170  # texto claro
    cols = np.where(mask.any(0))[0]
    rows = np.where(mask.any(1))[0]
    if len(cols) == 0 or len(rows) == 0:
        return None, 0.0
    sub = band[rows.min() : rows.max() + 1, cols.min() : cols.max() + 1]
    # segmenta dígitos por colunas com tinta
    colmask = (sub > 170).any(0)
    digits, run = [], []
    for i, on in enumerate(list(colmask) + [False]):
        if on:
            run.append(i)
        elif run:
            seg = sub[:, run[0] : run[-1] + 1]
            if seg.shape[1] >= 3:
                digits.append(seg)
            run = []
    if not digits:
        return None, 0.0
    out, scores = "", []
    for seg in digits:
        q = _norm(seg.astype(np.float32))
        d, sc = max(((d, _zncc(q, t)) for d, t in _T.digits.items()), key=lambda kv: kv[1])
        out += d
        scores.append(sc)
    try:
        return int(out), float(np.mean(scores))
    except ValueError:
        return None, 0.0


def recognize_table(img: Image.Image) -> RecognizedState:
    """Pipeline completo: imagem -> estado (hole/board/pot)."""
    rgb = np.asarray(img.convert("RGB"))
    gray = _gray(img)
    H = gray.shape[0]
    boxes = _find_cards(gray)
    reads = [( *_read_card(rgb, b), b) for b in boxes]  # (card, score, box)

    Wpx = gray.shape[1]
    hole, board, confs, hole_boxes = [], [], [], []
    for card, score, box in reads:
        x, y, w, h = box
        cy = y + h / 2
        confs.append(score)
        if cy > H * 0.66:
            hole.append((x, card))
            hole_boxes.append(box)
        else:
            board.append((x, card))
    hole = [c for _, c in sorted(hole)][:2]
    board = [c for _, c in sorted(board)][:5]
    pot, potc = _read_pot(rgb, gray)
    if pot is not None:
        confs.append(potc)

    # participantes + posição: assentos/botão por blob -> geometria (ordem de ação)
    seats, button = _locate_seats(rgb)
    if hole_boxes:  # herói fica onde estão as cartas do herói
        hero = (float(np.mean([b[0] + b[2] / 2 for b in hole_boxes])),
                float(np.mean([b[1] + b[3] / 2 for b in hole_boxes])))
    else:
        hero = (Wpx / 2, H * 0.9)
    n_players, position = (derive_position(seats, hero, button) if len(seats) >= 2 else (0, ""))

    return RecognizedState(
        hole=hole, board=board, pot=pot, n_cards=len(reads),
        confidence=round(float(np.mean(confs)) if confs else 0.0, 3),
        n_players=n_players, position=position,
    )
