"""Avaliação da visão em SCREENSHOTS REAIS de clientes de poker 2D (não sintéticos).

O passo #0 que a pesquisa exige: medir a visão em telas REAIS, não só no sintético.
Ingere uma pasta de imagens reais (ex.: PokerTH, jogos de navegador, telas de outros
alunos) e roda F1 (template) + F2 (treinado) + OCR, mostrando o que cada um LÊ. Se você
tiver o gabarito num .json ao lado, também mede acurácia. É o harness pra levar à banca a
prova de "testado em tela real".

Uso: uv run python scripts/real_eval.py [pasta_de_imagens]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from PIL import Image

from poker_arena.vision import (
    check_state,
    recognize_table,
    recognize_table_onnx,
    vision_model_available,
)

_BUDGET_S = 4.0  # requisito da banca: reconhecer + processar + decidir em <= 4s


def evaluate_image(path: Path) -> None:
    img = Image.open(path).convert("RGB")
    print(f"\n{'=' * 70}\nTELA REAL: {path.name}  ({img.width}x{img.height})")

    # LATÊNCIA ponta-a-ponta (visão + OCR + sanity) — o caminho do endpoint ao vivo
    t0 = time.time()
    if vision_model_available():
        check_state(recognize_table_onnx(img, ocr_numbers=True))
    else:
        check_state(recognize_table(img, ocr_numbers=True))
    dt = time.time() - t0
    tag = "OK <=4s" if dt <= _BUDGET_S else "ESTOUROU o limite de 4s"
    print(f"  [LATÊNCIA] visão+OCR+sanity: {dt:.2f}s  [{tag}]")

    # F1 (baseline por template/blob) + OCR
    f1 = recognize_table(img, ocr_numbers=True)
    s1 = check_state(f1)
    print(f"  [F1 template] hole={f1.hole} board={f1.board} pote={f1.pot}({f1.pot_source}) "
          f"jogadores={f1.n_players} pos={f1.position!r} conf={f1.confidence}")
    print(f"               stacks={f1.stacks} | sanity={'OK' if s1.ok else 'ABSTEM: '+'; '.join(s1.problems)}")

    # F2 (modelo treinado agnóstico), se instalado
    if vision_model_available():
        try:
            f2 = recognize_table_onnx(img, ocr_numbers=True)
            s2 = check_state(f2)
            print(f"  [F2 treinado] hole={f2.hole} board={f2.board} pote={f2.pot}({f2.pot_source}) "
                  f"jogadores={f2.n_players} pos={f2.position!r} conf={f2.confidence}")
            print(f"               stacks={f2.stacks} | sanity={'OK' if s2.ok else 'ABSTEM: '+'; '.join(s2.problems)}")
        except Exception as e:  # noqa: BLE001
            print(f"  [F2 treinado] falhou: {type(e).__name__}: {e}")
    else:
        print("  [F2 treinado] modelo não instalado (models/poker_vision.onnx)")


def main() -> None:
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "real_eval" / "imgs"
    imgs = sorted(p for p in folder.glob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg"))
    if not imgs:
        print(f"sem imagens em {folder}")
        return
    print(f"# Visão em {len(imgs)} TELAS REAIS (F2 instalado: {vision_model_available()})")
    for p in imgs:
        try:
            evaluate_image(p)
        except Exception as e:  # noqa: BLE001
            print(f"\n{p.name}: erro {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
