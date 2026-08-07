"""Gera o logo do Poker Arena como .ico multi-resolução (e um .png de preview).

Visual: feltro verde de cassino (gradiente radial) + anel dourado + espada creme
com sombra suave — lê como "poker" na hora.
"""

import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

S = 256
OUT_ICO = os.path.join(os.path.dirname(__file__), "poker.ico")
OUT_PNG = os.path.join(os.path.dirname(__file__), "poker.png")

GREEN_IN = (28, 150, 105)  # feltro claro (centro)
GREEN_OUT = (7, 44, 31)  # feltro escuro (borda)
GOLD = (201, 162, 90)
CREAM = (245, 247, 250)

# --- fundo: gradiente radial emerald num retângulo arredondado ---
grad = Image.new("RGB", (S, S))
px = grad.load()
cx = cy = S / 2.0
maxd = (cx * cx + cy * cy) ** 0.5
for y in range(S):
    for x in range(S):
        t = min(1.0, ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 / maxd)
        px[x, y] = (
            int(GREEN_IN[0] * (1 - t) + GREEN_OUT[0] * t),
            int(GREEN_IN[1] * (1 - t) + GREEN_OUT[1] * t),
            int(GREEN_IN[2] * (1 - t) + GREEN_OUT[2] * t),
        )
grad = grad.convert("RGBA")

img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([6, 6, S - 6, S - 6], radius=54, fill=255)
img.paste(grad, (0, 0), mask)

# --- anel dourado duplo ---
d = ImageDraw.Draw(img)
d.rounded_rectangle([16, 16, S - 16, S - 16], radius=44, outline=GOLD, width=6)
d.rounded_rectangle(
    [26, 26, S - 26, S - 26], radius=36, outline=(GOLD[0], GOLD[1], GOLD[2]), width=2
)


def load_font(size):
    for name in ("seguisym.ttf", "arial.ttf", "DejaVuSans.ttf"):
        for base in (r"C:\Windows\Fonts", "/usr/share/fonts/truetype/dejavu"):
            p = os.path.join(base, name)
            if os.path.exists(p):
                try:
                    candidate = ImageFont.truetype(p, size)
                except (OSError, ValueError):
                    candidate = None
                if candidate is not None:
                    return candidate
    return ImageFont.load_default()


spade = "♠"
font = load_font(150)

# sombra
sh = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(sh).text((cx, cy + 10), spade, font=font, fill=(0, 0, 0, 150), anchor="mm")
img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(5)))
# espada
ImageDraw.Draw(img).text((cx, cy), spade, font=font, fill=CREAM, anchor="mm")

sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
img.save(OUT_ICO, format="ICO", sizes=sizes)
img.save(OUT_PNG)
print("OK ->", OUT_ICO)
print("glyph box?", font.getbbox(spade))
