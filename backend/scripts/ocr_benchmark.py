"""Benchmark REPRODUZÍVEL do OCR de números (pote + stacks) — o que fecha o overclaim.

As acurácias de pote/stacks precisam ser AUDITÁVEIS: um script que qualquer um roda e
obtém o mesmo número, não um valor solto numa mensagem de commit. Este é esse script.

Gera N mesas SINTÉTICAS com gabarito (pote + fichas por assento conhecidos), roda o
reconhecedor com OCR ligado e mede:

  * POTE (exato) no CAMINHO RÁPIDO (`deep_stacks=False`) — uma otimização cujo tempo
    ainda precisa ser medido no hardware e corpus alvo.
  * POTE (exato) no caminho PROFUNDO (deep_stacks=True, análise offline).
  * STACKS (recall por valor) no caminho profundo: um valor de stack do gabarito conta
    como lido se aparece no multiconjunto de stacks reconhecidos (casa 1-a-1, sem
    recontar). Métrica de recall honesta — sujeita a colisão rara de valores (5..300).
  * LATÊNCIA (média/p95) de cada caminho.

Reprodutível: seeds fixas (0..N-1). ATENÇÃO ao escopo destes números — eles são no estilo
CANÔNICO sintético, que é EXATAMENTE o estilo em que o pipeline F1 é calibrado. Portanto:
NÃO são held-out de estilo de UI (os outros estilos não são testados aqui) e NÃO são tela
REAL — em screenshots reais não vistos a leitura NÃO transfere (gap sim→real; ver
scripts/real_eval/RESULTADO.md, onde o mesmo OCR leu lixo no PokerTH). É a régua do domínio
calibrado, não a prova de agnosticismo. Reporta o número que SAIR — sem alvo.
Uso: uv run python scripts/ocr_benchmark.py [N]
"""

from __future__ import annotations

import sys
import time
from collections import Counter

from poker_arena.vision import ocr
from poker_arena.vision.recognize import recognize_table
from poker_arena.vision.synth import CANONICAL, render_table


def _pct(a: int, b: int) -> str:
    return f"{100 * a / b:.1f}%" if b else "n/a"


def _p95(xs: list[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))]


def _stack_recall(truth_stacks: list[int], read_stacks: dict[int, int] | None) -> tuple[int, int]:
    """(acertos, total): quantos valores de stack do gabarito foram lidos (casamento por
    multiconjunto, cada leitura casa no máximo um gabarito). Total = nº de assentos."""
    total = len(truth_stacks)
    if not read_stacks:
        return 0, total
    have = Counter(read_stacks.values())
    hits = 0
    for v in truth_stacks:
        if have.get(v, 0) > 0:
            have[v] -= 1
            hits += 1
    return hits, total


def main() -> None:
    if not ocr.available():
        print("RapidOCR não instalado — `uv sync` pra instalar rapidocr-onnxruntime. Abortando.")
        return
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 80

    # aquecimento (não conta na latência): 1ª leitura carrega os modelos
    warm, _ = render_table(seed=99991, style=CANONICAL, with_seats=True, n_board=3)
    recognize_table(warm, ocr_numbers=True, deep_stacks=True)

    pot_fast_ok = pot_deep_ok = 0
    stack_hits = stack_tot = 0
    t_fast: list[float] = []
    t_deep: list[float] = []

    print(f"# Benchmark OCR — {n} mesas sintéticas (estilo CANÔNICO, seeds 0..{n - 1})")
    for seed in range(n):
        img, truth = render_table(seed=seed, style=CANONICAL, with_seats=True, n_board=3)

        t0 = time.time()  # CAMINHO RÁPIDO: pote por ROI central; sem promessa de SLA
        fast = recognize_table(img, ocr_numbers=True, deep_stacks=False)
        t_fast.append(time.time() - t0)
        pot_fast_ok += int(fast.pot == truth["pot"])

        t0 = time.time()  # CAMINHO PROFUNDO (offline): pote global + stacks por assento
        deep = recognize_table(img, ocr_numbers=True, deep_stacks=True)
        t_deep.append(time.time() - t0)
        pot_deep_ok += int(deep.pot == truth["pot"])
        h, tot = _stack_recall(truth["stacks"], deep.stacks)
        stack_hits += h
        stack_tot += tot

    print(f"\nPOTE  (caminho RÁPIDO / produção): {_pct(pot_fast_ok, n)}  ({pot_fast_ok}/{n})")
    print(f"POTE  (caminho PROFUNDO / offline): {_pct(pot_deep_ok, n)}  ({pot_deep_ok}/{n})")
    print(
        f"STACKS (recall por valor, profundo): {_pct(stack_hits, stack_tot)} "
        f" ({stack_hits}/{stack_tot})"
    )
    print(f"\nLATÊNCIA rápido : média {sum(t_fast) / n:.2f}s  p95 {_p95(t_fast):.2f}s")
    print(f"LATÊNCIA profundo: média {sum(t_deep) / n:.2f}s  p95 {_p95(t_deep):.2f}s")
    print("\n(seeds fixas -> reexecutar dá o MESMO número. Estilo CANÔNICO sintético = o")
    print(" estilo CALIBRADO do F1; NÃO é held-out de estilo nem tela real. Em tela real")
    print(" não vista a leitura não transfere — ver scripts/real_eval/RESULTADO.md.)")


if __name__ == "__main__":
    main()
