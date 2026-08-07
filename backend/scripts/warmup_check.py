"""Mede cold-start e inferências subsequentes para uma imagem e máquina específicas.

Um registro anterior observou diferença entre a primeira leitura e as seguintes. O servidor
tenta aquecer dependências no boot, mas o warmup é assíncrono e best-effort: uma requisição
pode chegar antes dele ou usar outro formato. Este script não prova SLA global.

O script mede a leitura fria e quatro subsequentes no mesmo processo. Uso:
    uv run python scripts/warmup_check.py [pasta_ou_imagem]

ATENÇÃO: o número COLD impresso é o WALL-TIME TOTAL da 1ª leitura (load do modelo + a
inferência), então varia com o TAMANHO/conteúdo da imagem e com a máquina — NÃO é constante.
Sem argumento, usa uma mesa sintética. O tag [OK/ESTOUROU] é relativo apenas à
imagem/máquina desta execução; um gate de release deve medir p50/p95 no corpus e hardware
alvo, inclusive concorrência e cold start."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from poker_arena.vision import (
    recognize_table,
    recognize_table_onnx,
    vision_model_available,
)

_BUDGET_S = 4.0
_WARM_REPS = 4


@dataclass(frozen=True)
class ReadResult:
    state: Any
    engine: str
    f2_error: Exception | None = None


def _read(img: Image.Image) -> ReadResult:
    if vision_model_available():
        try:
            return ReadResult(recognize_table_onnx(img, ocr_numbers=True), "F2-onnx")
        except Exception as exc:  # noqa: BLE001 - fallback is reported and makes the gate incomplete
            return ReadResult(
                recognize_table(img, ocr_numbers=True),
                "F1-template-fallback",
                f2_error=exc,
            )
    return ReadResult(recognize_table(img, ocr_numbers=True), "F1-template")


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


def main() -> int:
    img, name = _load_image()

    t0 = time.perf_counter()
    cold_result = _read(img)  # FRIA: carrega sessão ONNX + engine RapidOCR + 1ª inferência
    cold = time.perf_counter() - t0

    warm: list[float] = []
    warm_results: list[ReadResult] = []
    for _ in range(_WARM_REPS):
        t0 = time.perf_counter()
        warm_results.append(_read(img))
        warm.append(time.perf_counter() - t0)
    warm_avg = sum(warm) / len(warm)
    results = [cold_result, *warm_results]
    engines = {result.engine for result in results}
    print(f"# Warmup check — imagem: {name} | engines: {', '.join(sorted(engines))}\n")

    def tag(dt: float) -> str:
        return "OK <=4s" if dt <= _BUDGET_S else "ESTOUROU 4s"

    print(f"COLD  (1ª leitura, carrega modelos): {cold:5.2f}s  [{tag(cold)}]  <- pago no boot")
    print(
        f"WARM  (média de {_WARM_REPS} leituras): {warm_avg:5.2f}s  [{tag(warm_avg)}]  "
        f"<- o que o usuário experimenta"
    )
    print(f"WARM  detalhe: {', '.join(f'{w:.2f}s' for w in warm)}")
    if name.startswith("sintética"):
        print("  (imagem sintética; não transfira estes tempos para screenshots reais.)")
    print()
    fallbacks = [result for result in results if result.f2_error is not None]
    if fallbacks:
        error_types = sorted({type(result.f2_error).__name__ for result in fallbacks})
        print(
            "=> EVIDENCE GATE: INCOMPLETE — o artefato F2 estava disponível, mas "
            f"{len(fallbacks)}/{len(results)} leituras caíram para F1 "
            f"({', '.join(error_types)})."
        )
        return 2
    if cold > _BUDGET_S >= warm_avg:
        print("=> Nesta amostra o warmup separa cold e warm; isso não garante que a 1ª")
        print("   requisição chegue depois do aquecimento nem que outras imagens fiquem em 4s.")
    elif warm_avg <= _BUDGET_S:
        print(f"=> Leituras subsequentes desta imagem ficaram no alvo; cold foi {cold:.2f}s.")
    else:
        print("=> ATENÇÃO: regime quente acima de 4s nesta máquina — investigar (CPU/imagem).")
    return 0 if warm_avg <= _BUDGET_S else 1


if __name__ == "__main__":
    raise SystemExit(main())
