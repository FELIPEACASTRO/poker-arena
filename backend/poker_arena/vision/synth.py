"""Gerador SINTÉTICO de mesas de poker 2D (cartas chapadas) — dados + gabarito.

Isto é o coração da estratégia agnóstica: em vez de depender das UIs reais, geramos
variação massiva no EIXO ESTILO-DE-UI (fonte, cores, feltro, tema, escala, posição,
deck 2-cores E 4-cores) e treinamos/testamos nisso. Cada imagem vem com o ESTADO
verdadeiro (gabarito), então dá pra medir acurácia de verdade — inclusive a QUEDA
em estilos não vistos (a prova que a banca precisa).

F1 usa isto pra testar o reconhecedor offline; F2 (Colab) usa a mesma ideia em
escala pra treinar o detector agnóstico.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFont

RANKS = "23456789TJQKA"
SUITS = "shdc"
_SUIT_SYM = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}  # ♠♥♦♣
_RANK_DISP = {"T": "10"}

_FONT_DIR = "C:/Windows/Fonts/"
_FONTS = ["arial.ttf", "arialbd.ttf", "verdana.ttf", "tahoma.ttf", "segoeui.ttf",
          "times.ttf", "cour.ttf"]

# esquemas de cor de naipe: 2-cores (clássico) e 4-cores (♦ azul, ♣ verde)
TWO_COLOR = {"s": (20, 20, 20), "c": (20, 20, 20), "h": (200, 30, 40), "d": (200, 30, 40)}
FOUR_COLOR = {"s": (20, 20, 20), "c": (20, 120, 40), "h": (200, 30, 40), "d": (30, 90, 210)}

_FELTS = [(28, 92, 60), (24, 78, 96), (40, 46, 58), (60, 40, 46), (30, 70, 50), (18, 40, 70)]


@dataclass(frozen=True)
class Style:
    """Um 'jeito de tela': fonte + esquema de cor + feltro + tamanho da carta."""

    name: str
    font: str
    suit_colors: dict = field(default_factory=lambda: TWO_COLOR)
    felt: tuple = (28, 92, 60)
    card_w: int = 60
    card_bg: tuple = (245, 245, 240)


# uma paleta de estilos "conhecidos" (variação real entre telas)
STYLES: list[Style] = [
    Style("classic-green", "arial.ttf", TWO_COLOR, _FELTS[0], 62),
    Style("blue-4color", "verdana.ttf", FOUR_COLOR, _FELTS[1], 58),
    Style("dark-bold", "arialbd.ttf", TWO_COLOR, _FELTS[2], 66),
    Style("times-4color", "times.ttf", FOUR_COLOR, _FELTS[4], 60),
    Style("segoe-teal", "segoeui.ttf", TWO_COLOR, _FELTS[5], 56),
]
# estilo CANÔNICO do qual o reconhecedor F1 tira os templates
CANONICAL = STYLES[0]


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(_FONT_DIR + path, size)
    except OSError:
        return ImageFont.load_default(size=size)


def render_card(rank: str, suit: str, style: Style, w: int | None = None) -> Image.Image:
    """Uma carta chapada: retângulo claro + índice (rank+naipe) e naipe grande."""
    w = w or style.card_w
    h = int(w * 1.4)
    img = Image.new("RGB", (w, h), style.card_bg)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([1, 1, w - 2, h - 2], radius=max(4, w // 12),
                        outline=(170, 170, 170), width=1)
    color = style.suit_colors[suit]
    rd = _RANK_DISP.get(rank, rank)
    idx_font = _font(style.font, int(w * 0.34))
    sym_font = _font(style.font, int(w * 0.30))
    big_font = _font(style.font, int(w * 0.62))
    d.text((int(w * 0.08), int(h * 0.04)), rd, font=idx_font, fill=color)
    d.text((int(w * 0.10), int(h * 0.30)), _SUIT_SYM[suit], font=sym_font, fill=color)
    # naipe grande no centro
    bb = d.textbbox((0, 0), _SUIT_SYM[suit], font=big_font)
    d.text(((w - (bb[2] - bb[0])) / 2, h * 0.42), _SUIT_SYM[suit], font=big_font, fill=color)
    return img


def _deal(rng: random.Random, k: int) -> list[str]:
    deck = [r + s for r in RANKS for s in SUITS]
    rng.shuffle(deck)
    return deck[:k]


def render_table(
    seed: int | None = None,
    style: Style | None = None,
    n_board: int | None = None,
    noise: float = 0.15,
) -> tuple[Image.Image, dict]:
    """Mesa 2D com gabarito. Randomiza posição/escala/fundo/ruído dentro do estilo."""
    rng = random.Random(seed)
    style = style or rng.choice(STYLES)
    if n_board is None:
        n_board = rng.choice([0, 3, 3, 4, 5])
    cards = _deal(rng, 7)
    hole, board = cards[:2], cards[2 : 2 + n_board]

    W, H = 900, 600
    img = Image.new("RGB", (W, H), style.felt)
    d = ImageDraw.Draw(img)
    # leve gradiente/vinheta pra não ser fundo chapado perfeito
    d.ellipse([W * 0.1, H * 0.05, W * 0.9, H * 0.95],
              fill=tuple(min(255, c + 12) for c in style.felt))

    truth = {"hole": hole, "board": board, "pot": 0, "style": style.name,
             "four_color": style.suit_colors is FOUR_COLOR}

    def paste_card(card: str, cx: int, cy: int, scale: float) -> None:
        # clientes de poker 2D renderizam as cartas ALINHADAS (sem rotação) — fiel ao domínio
        cw = int(style.card_w * scale)
        ci = render_card(card[0], card[1], style, cw)
        img.paste(ci, (cx - ci.width // 2, cy - ci.height // 2))

    # board no centro (uma fileira) — folga clara entre as cartas
    if board:
        gap = int(style.card_w * 1.30)
        x0 = W // 2 - (len(board) - 1) * gap // 2
        by = H // 2 + rng.randint(-20, 10)
        for i, c in enumerate(board):
            paste_card(c, x0 + i * gap + rng.randint(-3, 3), by, rng.uniform(0.95, 1.06))
    # hole embaixo (herói) — as duas cartas lado a lado, com folga
    hx = W // 2 + rng.randint(-40, 40)
    hy = int(H * 0.82) + rng.randint(-12, 12)
    for i, c in enumerate(hole):
        paste_card(c, hx - 46 + i * 92, hy, rng.uniform(1.0, 1.1))

    # pote (texto) — posição variável dentro de uma região central
    pot = rng.choice([rng.randint(20, 300), rng.randint(300, 3000), rng.randint(3000, 40000)])
    truth["pot"] = pot
    pot_font = _font(style.font, rng.randint(26, 36))
    ptxt = f"{pot}"
    px = W // 2 + rng.randint(-60, 60)
    py = int(H * 0.30) + rng.randint(-20, 20)
    bb = d.textbbox((0, 0), ptxt, font=pot_font)
    truth["pot_box"] = (px - (bb[2] - bb[0]) // 2, py, bb[2] - bb[0], bb[3] - bb[1])
    d.text((px - (bb[2] - bb[0]) // 2, py), ptxt, font=pot_font, fill=(240, 235, 210))

    if noise > 0:  # ruído gaussiano leve (robustez / realismo)
        import numpy as np

        arr = np.asarray(img).astype("int16")
        n = np.random.default_rng(seed).normal(0, 8 * noise, arr.shape)
        arr = np.clip(arr + n, 0, 255).astype("uint8")
        img = Image.fromarray(arr)
    return img, truth
