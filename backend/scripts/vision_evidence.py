"""Gera a EVIDÊNCIA da visão F1 (pra banca): tabela de acurácia + imagens de exemplo.

Roda o reconhecedor em N mesas por estilo (calibrado × nunca visto) e mede acurácia
de cartas/hole/board/pote. A QUEDA nos estilos não vistos é a prova de que o baseline
por template não generaliza sozinho -> justifica o modelo treinado (F2). Salva também
imagens com o gabarito vs o detectado.

Uso: uv run python scripts/vision_evidence.py [saida_dir]
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

from poker_arena.vision import recognize_table, render_table
from poker_arena.vision.synth import CANONICAL, STYLES

N = 80


def measure(style) -> dict:
    cok = ctot = hx = bx = px = 0
    for seed in range(N):
        img, truth = render_table(seed=20000 + seed, style=style)
        st = recognize_table(img)
        tc = truth["hole"] + truth["board"]
        gc = st.hole + st.board
        ctot += len(tc)
        cok += sum(1 for c in tc if c in gc)
        hx += set(st.hole) == set(truth["hole"])
        bx += st.board == truth["board"]
        px += st.pot == truth["pot"]
    return {
        "cartas": 100 * cok / ctot,
        "hole": 100 * hx / N,
        "board": 100 * bx / N,
        "pote": 100 * px / N,
    }


def save_example(style, seed: int, out: Path) -> None:
    img, truth = render_table(seed=seed, style=style)
    st = recognize_table(img)
    canvas = Image.new("RGB", (img.width, img.height + 70), (10, 14, 20))
    canvas.paste(img, (0, 0))
    d = ImageDraw.Draw(canvas)
    ok = set(st.hole) == set(truth["hole"]) and st.board == truth["board"]
    d.text((12, img.height + 8),
           f"GABARITO  hole={truth['hole']} board={truth['board']} pot={truth['pot']}",
           fill=(180, 200, 220))
    verdict = "OK" if ok else "DIVERGIU"
    d.text((12, img.height + 34),
           f"DETECTADO hole={st.hole} board={st.board} pot={st.pot}  ->  {verdict}",
           fill=(120, 230, 140) if ok else (240, 170, 90))
    canvas.save(out / f"exemplo_{style.name}.png")


def main() -> None:
    default = Path(__file__).resolve().parent / "vision_evidence"
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else default
    out.mkdir(parents=True, exist_ok=True)

    rows = [("classic-green (CALIBRADO)", measure(CANONICAL), True)]
    for st in STYLES[1:]:
        rows.append((f"{st.name} (nunca visto)", measure(st), False))

    lines = [
        "# Evidência — Visão F1 (reconhecimento de mesa 2D)",
        "",
        f"Reconhecedor por template rodado em **{N} mesas por estilo**. O estilo *calibrado* é",
        "de onde saem os templates; os demais o reconhecedor **nunca viu** — a QUEDA neles é a",
        "prova de que o baseline por template **não generaliza sozinho**, o que justifica o",
        "modelo treinado agnóstico (F2, notebook Colab).",
        "",
        "| Estilo | Cartas | Hole exato | Board exato | Pote |",
        "|---|---|---|---|---|",
    ]
    for name, m, _ in rows:
        lines.append(
            f"| {name} | {m['cartas']:.1f}% | {m['hole']:.0f}% "
            f"| {m['board']:.0f}% | {m['pote']:.0f}% |"
        )
    seen = rows[0][1]["cartas"]
    unseen = sum(r[1]["cartas"] for r in rows[1:]) / (len(rows) - 1)
    lines += [
        "",
        f"**Calibrado: {seen:.1f}% de cartas** · **média nunca-visto: {unseen:.1f}%** → "
        f"queda de **{seen - unseen:.1f} pontos** = o gap de domínio que o modelo (F2) fecha.",
        "",
        "Imagens de exemplo (gabarito × detectado) salvas nesta pasta.",
    ]
    (out / "RELATORIO.md").write_text("\n".join(lines), encoding="utf-8")
    for st in STYLES:
        save_example(st, 20000, out)

    print("\n".join(lines))
    print(f"\n>>> evidência salva em {out}")


if __name__ == "__main__":
    main()
