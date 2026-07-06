"""Prova o WARMUP: mede o cold-start (1ª inferência, que CARREGA os modelos) vs o regime
quente (inferências seguintes). É a evidência auditável do requisito de <=4s da banca.

O achado da auditoria: na 1ª leitura de uma tela real o pipeline gastou ~5-6s — porque a
1ª inferência carrega a sessão ONNX + o engine RapidOCR. As leituras seguintes ficam ~2.4s.
O servidor agora AQUECE os modelos no boot (lifespan em api/app.py), então esse custo de
carga sai da 1ª requisição do usuário: ela já pega o regime quente.

Este script demonstra o mecanismo num único processo: mede a leitura FRIA (a que o warmup
paga no boot) e as QUENTES (as que o usuário realmente experimenta). Uso:
    uv run python scripts/warmup_check.py [pasta_ou_imagem]

ATENÇÃO: o número COLD impresso é o WALL-TIME TOTAL da 1ª leitura (load do modelo + a
inferência), então varia com o TAMANHO/conteúdo da imagem e com a máquina — NÃO é constante.
Sem argumento, usa uma mesa sintética 900x600 (COLD ~4,3s aqui); num screenshot REAL de
desktop (maior, mais texto p/ OCR) a auditoria mediu COLD ~6,6s e WARM ~2,4s. Portanto, pra
afirmar ≤4s nas telas reais da banca, RODE com um screenshot real do alvo. O tag [OK/ESTOUROU]
é relativo à imagem/máquina desta execução."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from PIL import Image

from poker_arena.vision import (
    recognize_table,
    recognize_table_onnx,
    vision_model_available,
)

_BUDGET_S = 4.0
_WARM_REPS = 4


def _read(img: Image.Image):
    if vision_model_available():
        try:
            return recognize_table_onnx(img, ocr_numbers=True)
        except Exception:
            return recognize_table(img, ocr_numbers=True)
    return recognize_table(img, ocr_numbers=True)


def _load_image() -> tuple[Image.Image, str]:
    if len(sys.argv) > 1:
        p = Path(sys.argv[1])
        if p.is_dir():
            imgs = sorted(q for q in p.glob("*") if q.suffix.lower() in (".png", ".jpg", ".jpeg"))
            if imgs:
                return Image.open(imgs[0]).convert("RGB"), imgs[0].name
        elif p.exists():
            return Image.open(p).convert("RGB"), p.name
    from poker_arena.vision.synth import CANONICAL, render_table

    img, _ = render_table(seed=7, style=CANONICAL, with_seats=True, n_board=5)
    return img, "sintética (canônica)"


def main() -> None:
    img, name = _load_image()
    engine = "F2-onnx" if vision_model_available() else "F1-template"
    print(f"# Warmup check — imagem: {name}  | engine: {engine}\n")

    t0 = time.time()
    _read(img)  # FRIA: carrega sessão ONNX + engine RapidOCR + 1ª inferência
    cold = time.time() - t0

    warm = []
    for _ in range(_WARM_REPS):
        t0 = time.time()
        _read(img)
        warm.append(time.time() - t0)
    warm_avg = sum(warm) / len(warm)

    def tag(dt: float) -> str:
        return "OK <=4s" if dt <= _BUDGET_S else "ESTOUROU 4s"

    print(f"COLD  (1ª leitura, carrega modelos): {cold:5.2f}s  [{tag(cold)}]  <- pago no boot")
    print(f"WARM  (média de {_WARM_REPS} leituras): {warm_avg:5.2f}s  [{tag(warm_avg)}]  "
          f"<- o que o usuário experimenta")
    print(f"WARM  detalhe: {', '.join(f'{w:.2f}s' for w in warm)}")
    if name.startswith("sintética"):
        print("  (imagem sintética 900x600; COLD é wall-time e CRESCE com telas reais maiores —")
        print("   auditoria mediu ~6,6s COLD / ~2,4s WARM no PokerTH. Rode com screenshot real.)")
    print()
    if cold > _BUDGET_S >= warm_avg:
        print("=> Sem warmup, a 1ª requisição estouraria 4s. Com o warmup no boot, TODA")
        print("   requisição do usuário (inclusive a 1ª) fica no regime quente, dentro de 4s.")
    elif warm_avg <= _BUDGET_S:
        print(f"=> Regime quente dentro do orçamento; cold-start já era {cold:.2f}s nesta máquina.")
    else:
        print("=> ATENÇÃO: regime quente acima de 4s nesta máquina — investigar (CPU/imagem).")


if __name__ == "__main__":
    main()
