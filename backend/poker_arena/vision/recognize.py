"""Reconhecedor F1 (baseline sintético): imagem 2D -> estado, por template + cor.

MODULAR: (1) LOCALIZA cartas (segmentação por brilho), (2) LÊ rank+naipe de cada uma
(template + cor do naipe), (3) separa herói/board por posição, (4) lê o pote (dígitos
por template). É o baseline offline pra provar o pipeline e MEDIR acurácia — inclusive
a queda em estilos não vistos. Isso não demonstra transferência para screenshots reais.

Nada de deep learning aqui de propósito: prova que a cadeia imagem->estado->decisão
funciona e dá uma régua sintética. Generalização real exige imagens rotuladas separadas.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .seats import derive_position
from .synth import _RANK_DISP, _SUIT_SYM, CANONICAL, RANKS, SUITS, Style, _font

_TH = 150  # brilho acima disso = interior de carta (claro sobre feltro escuro)
_TEMPL = (34, 26)  # tamanho canônico de template (h, w)
_COLORS = {
    "black": (20, 20, 20),
    "red": (200, 30, 40),
    "blue": (30, 90, 210),
    "green": (20, 120, 40),
}
_SUIT_BY_COLOR = {"black": ("s", "c"), "red": ("h", "d"), "blue": ("d",), "green": ("c",)}
_VALID_CARDS = {rank + suit for rank in RANKS for suit in SUITS}

Box = tuple[int, int, int, int]
Point = tuple[float, float]


@dataclass
class RecognizedState:
    """O que a visão extraiu (antes do sanity-check)."""

    hole: list[str] = field(default_factory=list)
    board: list[str] = field(default_factory=list)
    pot: int | None = None
    n_cards: int = 0
    confidence: float = 0.0  # sem evidência explícita, o estado nasce não confiável
    card_confidences: list[float] = field(default_factory=list)
    pot_confidence: float | None = None
    n_players: int = 0  # participantes na mesa (0 = não detectado)
    position: str = ""  # posição do herói (BTN/SB/BB/UTG/...) — "" se indefinida
    stacks: dict[int, int] | None = None  # fichas lidas por assento (OCR) — None se não leu
    stack_confidences: dict[int, float] | None = None
    pot_source: str = "template"  # de onde veio o pote: "ocr" (forte) ou "template" (fraco)


def _gray(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("L"), dtype=np.uint8)


def _glyph(text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> np.ndarray:
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


def _bounded_similarity(value: float) -> float:
    """Keep diagnostic similarity inside the API score contract.

    ZNCC is a similarity in ``[-1, 1]``, not a calibrated probability.  Negative
    correlation carries no useful positive confidence, so diagnostics expose it as
    zero.  Production authorization remains separately blocked for the F1 baseline.
    """

    return max(0.0, min(1.0, float(value)))


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
    """Propõe cartas como regiões claras de proporção aproximada 1.4.

    Os limiares escalam com a largura, mas isso é somente invariância geométrica do
    algoritmo; não demonstra exatidão em monitores, clientes ou temas não avaliados.
    """
    H, W = gray.shape
    scale = max(1, round(W / 300))  # custo normalizado por largura; qualidade é medida à parte
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
    F1 (estilo canônico); F2 é apenas um candidato e também precisa de benchmark
    cego por cliente/sessão/tema antes de qualquer alegação de generalização."""
    H, W = rgb.shape[:2]
    scale = max(1, round(W / 300))
    small = np.asarray(Image.fromarray(rgb).resize((max(1, W // scale), max(1, H // scale))))
    s16 = small.astype(np.int16)
    r, g, b = s16[..., 0], s16[..., 1], s16[..., 2]
    mx = small.max(2)
    # disco azulado (não claro). b>g+25 exige o azul dominar MAIS que o feltro azul-esverdeado
    # (ex.: blue-4color (24,78,96): 96>103 falso -> excluído), mantendo os avatares (b-g >= ~40)
    seat_mask = (b > r + 12) & (b > g + 25) & (b > 100) & (mx < 205)
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
    # sem assumir que a acurácia em carta isolada transfere ao contexto da mesa.
    g0 = np.asarray(Image.fromarray(card).convert("L"))
    ys, xs = np.where(g0 > 150)
    if len(xs) > 20:
        card = card[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    # Proportional crops below must use the tightened card, not stale detector dimensions.
    h, w = card.shape[:2]
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
        return rank + cands[0], _bounded_similarity(rscore)
    big_g = 255 - gray[int(h * 0.52) : int(h * 0.94), int(w * 0.18) : int(w * 0.82)]
    sq = _norm(big_g)
    suit, sscore = max(((s, _zncc(sq, _T.suits[s])) for s in cands), key=lambda kv: kv[1])
    return rank + suit, _bounded_similarity(min(rscore, sscore))


def _read_pot(gray: np.ndarray, card_boxes: Sequence[Box] = ()) -> tuple[int | None, float]:
    """Lê o pote: região de texto claro na faixa central-superior (heurística F1).

    APAGA as cartas já detectadas antes de ler: o topo claro do board caía na faixa do
    pote e se fundia aos dígitos, produzindo um pote silenciosamente ERRADO em mãos com
    board. Sem as cartas contaminando, a segmentação de dígitos fica limpa."""
    H, W = gray.shape
    g = gray.copy()
    for x, y, w, h in card_boxes:  # zera (escurece) cada carta detectada
        g[max(0, int(y)) : int(y + h), max(0, int(x)) : int(x + w)] = 0
    band = g[int(H * 0.18) : int(H * 0.40), int(W * 0.30) : int(W * 0.70)]
    mask = band > 170  # texto claro
    cols = np.where(mask.any(0))[0]
    rows = np.where(mask.any(1))[0]
    if len(cols) == 0 or len(rows) == 0:
        return None, 0.0
    sub = band[rows.min() : rows.max() + 1, cols.min() : cols.max() + 1]
    # segmenta dígitos por colunas com tinta
    colmask = np.asarray((sub > 170).any(axis=0), dtype=np.bool_)
    digits: list[np.ndarray] = []
    run: list[int] = []
    for i, on in enumerate(colmask.tolist() + [False]):
        if on:
            run.append(i)
        elif run:
            seg = sub[:, run[0] : run[-1] + 1]
            if seg.shape[1] >= 3:
                digits.append(seg)
            run = []
    if not digits:
        return None, 0.0
    out = ""
    scores: list[float] = []
    for seg in digits:
        q = _norm(seg.astype(np.float32))
        d, sc = max(((d, _zncc(q, t)) for d, t in _T.digits.items()), key=lambda kv: kv[1])
        out += d
        scores.append(sc)
    try:
        return int(out), _bounded_similarity(float(np.mean(scores)))
    except ValueError:
        return None, 0.0


def _read_numbers(
    rgb: np.ndarray,
    gray: np.ndarray,
    card_boxes: Sequence[Box],
    seats: Sequence[Point],
    ocr_numbers: bool,
    deep_stacks: bool = False,
) -> tuple[int | None, float, dict[int, int] | None, dict[int, float] | None, str]:
    """Lê pote (+ stacks se `deep_stacks`). OCR forte quando pedido e disponível; senão o
    template (fraco). `deep_stacks=False` (padrão) = caminho de BAIXA LATÊNCIA (<=4s): só o
    pote; True lê também os stacks por assento (offline). Devolve (pote, conf, stacks, fonte)."""
    if ocr_numbers:
        from . import ocr  # import tardio: rapidocr só quando o OCR é usado

        if ocr.available():
            H, W = gray.shape
            sn = ocr.read_screen(rgb, W, H, list(card_boxes), list(seats), deep_stacks=deep_stacks)
            if sn.pot is not None:
                return sn.pot, sn.pot_conf, sn.stacks, sn.stack_confidences, "ocr"
    pot, potc = _read_pot(gray, card_boxes)
    return pot, potc, None, None, "template"


def _cards_force_abstention(
    hole: Sequence[str],
    board: Sequence[str],
    confidences: Sequence[float],
    threshold: float | None,
) -> bool:
    """Whether card evidence alone already makes strict acceptance impossible.

    This mirrors only the card-related, fail-closed subset of ``check_state``. It is
    used solely to avoid OCR that cannot rescue an already invalid state; the complete
    sanity gate still runs after recognition.
    """
    if threshold is None:
        return False
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise ValueError("fail_fast_abstain_below must be a finite number between 0 and 1")
    threshold = float(threshold)
    if not math.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
        raise ValueError("fail_fast_abstain_below must be a finite number between 0 and 1")
    cards = [*hole, *board]
    if len(hole) != 2 or len(board) not in (0, 3, 4, 5):
        return True
    if any(card not in _VALID_CARDS for card in cards) or len(set(cards)) != len(cards):
        return True
    if len(confidences) != len(cards):
        return True
    return any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0.0 <= float(value) <= 1.0
        or float(value) < threshold
        for value in confidences
    )


def recognize_table(
    img: Image.Image,
    ocr_numbers: bool = False,
    deep_stacks: bool = False,
    fail_fast_abstain_below: float | None = None,
) -> RecognizedState:
    """Pipeline completo: imagem -> estado (hole/board/pot [+ stacks]).

    `ocr_numbers=True` tenta ler pote e stacks por OCR quando o RapidOCR está
    instalado; senão cai no leitor por template (fraco). Padrão False = rápido (testes)."""
    rgb = np.asarray(img.convert("RGB"))
    gray = _gray(img)
    H = gray.shape[0]
    boxes = _find_cards(gray)
    reads = [(*_read_card(rgb, b), b) for b in boxes]  # (card, score, box)

    Wpx = gray.shape[1]
    hole_candidates, board_candidates = [], []
    for card, score, box in reads:
        x, y, w, h = box
        cy = y + h / 2
        if cy > H * 0.66:
            hole_candidates.append((x, score, card, box))
        else:
            board_candidates.append((x, score, card, box))
    hole_selected = sorted(hole_candidates, key=lambda t: t[1], reverse=True)[:2]
    board_selected = sorted(board_candidates, key=lambda t: t[1], reverse=True)[:5]
    hole_selected.sort(key=lambda t: t[0])
    board_selected.sort(key=lambda t: t[0])
    hole = [c for _, _, c, _ in hole_selected]
    board = [c for _, _, c, _ in board_selected]
    card_confs = [float(sc) for _, sc, _, _ in hole_selected + board_selected]
    hole_boxes = [box for _, _, _, box in hole_selected]

    # participantes + posição: assentos/botão por blob -> geometria (ordem de ação)
    seats, button = _locate_seats(rgb)
    if hole_boxes:  # herói fica onde estão as cartas do herói
        hero = (
            float(np.mean([b[0] + b[2] / 2 for b in hole_boxes])),
            float(np.mean([b[1] + b[3] / 2 for b in hole_boxes])),
        )
    else:
        hero = (Wpx / 2, H * 0.9)
    n_players, position = derive_position(seats, hero, button) if len(seats) >= 2 else (0, "")

    if ocr_numbers and _cards_force_abstention(hole, board, card_confs, fail_fast_abstain_below):
        pot, potc, stacks, stack_confs, src = None, 0.0, None, None, "skipped-card-gate"
    else:
        pot, potc, stacks, stack_confs, src = _read_numbers(
            rgb, gray, boxes, seats, ocr_numbers, deep_stacks
        )
    confs = list(card_confs)
    if pot is not None:
        confs.append(potc)

    return RecognizedState(
        hole=hole,
        board=board,
        pot=pot,
        n_cards=len(hole) + len(board),
        confidence=round(float(np.mean(confs)) if confs else 0.0, 3),
        card_confidences=card_confs,
        pot_confidence=float(potc) if pot is not None else None,
        n_players=n_players,
        position=position,
        stacks=stacks,
        stack_confidences=stack_confs,
        pot_source=src,
    )
