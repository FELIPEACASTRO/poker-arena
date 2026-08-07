"""Gera a EVIDÊNCIA da visão F1 (pra banca): tabela de acurácia + imagens de exemplo.

Compara o antigo banco canônico com o banco multiestilo de produção e mede também
dois estilos sintéticos realmente retidos da calibração. Nenhum resultado sintético
prova desempenho de F2 ou transferência para screenshots reais.

Uso: uv run python scripts/vision_evidence.py [saida_dir]
"""

from __future__ import annotations

import json
import platform
import sys
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageDraw

from poker_arena.vision import recognize_table, render_table
from poker_arena.vision.recognize import _CANONICAL_T, RecognizedState, _recognize_table
from poker_arena.vision.synth import FOUR_COLOR, STYLES, TWO_COLOR, Style

N = 80
HELD_OUT_STYLES = (
    Style("holdout-tahoma", "tahoma.ttf", TWO_COLOR, (60, 40, 46), 64),
    Style("holdout-courier-4color", "cour.ttf", FOUR_COLOR, (30, 70, 50), 60),
)
Recognizer = Callable[[Image.Image], RecognizedState]


def card_detection_counts(truth_cards: list[str], predicted_cards: list[str]) -> dict[str, int]:
    """Counts for precision/recall; duplicates and extra predictions are not free."""
    truth_counter = Counter(truth_cards)
    predicted_counter = Counter(predicted_cards)
    true_positive = sum((truth_counter & predicted_counter).values())
    return {"tp": true_positive, "truth": len(truth_cards), "pred": len(predicted_cards)}


def is_exact_state(state, truth: dict) -> bool:
    """Exact full state used by the evidence report (hole order is immaterial)."""
    return (
        len(state.hole) == 2
        and set(state.hole) == set(truth["hole"])
        and state.board == truth["board"]
        and state.pot == truth["pot"]
        and state.n_players == truth["n_players"]
        and state.position == truth["position"]
    )


def measure(style: Style, recognizer: Recognizer = recognize_table) -> dict[str, float]:
    tp = truth_n = pred_n = hx = bx = px = npl = pos = abst = exact = 0
    for seed in range(N):
        img, truth = render_table(seed=20000 + seed, style=style, with_seats=True)
        st = recognizer(img)
        tc = truth["hole"] + truth["board"]
        gc = st.hole + st.board
        counts = card_detection_counts(tc, gc)
        tp += counts["tp"]
        truth_n += counts["truth"]
        pred_n += counts["pred"]
        hx += set(st.hole) == set(truth["hole"])
        bx += st.board == truth["board"]
        px += st.pot == truth["pot"]
        npl += st.n_players == truth["n_players"]
        pos += st.position == truth["position"]
        abst += st.n_players == 0
        exact += is_exact_state(st, truth)
    precision = tp / pred_n if pred_n else 0.0
    recall = tp / truth_n if truth_n else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "cartas": 100 * f1,
        "precisao": 100 * precision,
        "recall": 100 * recall,
        "hole": 100 * hx / N,
        "board": 100 * bx / N,
        "pote": 100 * px / N,
        "jogadores": 100 * npl / N,
        "posicao": 100 * pos / N,
        "absteve": 100 * abst / N,
        "estado_exato": 100 * exact / N,
    }


def save_example(style, seed: int, out: Path) -> None:
    img, truth = render_table(seed=seed, style=style, with_seats=True)
    st = recognize_table(img)
    canvas = Image.new("RGB", (img.width, img.height + 96), (10, 14, 20))
    canvas.paste(img, (0, 0))
    d = ImageDraw.Draw(canvas)
    ok = is_exact_state(st, truth)
    d.text(
        (12, img.height + 8),
        f"GABARITO  hole={truth['hole']} board={truth['board']} pot={truth['pot']} "
        f"jogadores={truth['n_players']} pos={truth['position']}",
        fill=(180, 200, 220),
    )
    verdict = "OK" if ok else "DIVERGIU"
    d.text(
        (12, img.height + 34),
        f"DETECTADO hole={st.hole} board={st.board} pot={st.pot} "
        f"jogadores={st.n_players} pos={st.position!r}  ->  {verdict}",
        fill=(120, 230, 140) if ok else (240, 170, 90),
    )
    canvas.save(out / f"exemplo_{style.name}.png")


def main() -> None:
    default = Path(__file__).resolve().parent / "vision_evidence"
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else default
    out.mkdir(parents=True, exist_ok=True)

    def canonical_only(image: Image.Image) -> RecognizedState:
        return _recognize_table(image, _CANONICAL_T)

    baseline_rows = [(style.name, measure(style, canonical_only)) for style in STYLES]
    production_rows = [(style.name, measure(style)) for style in STYLES]
    holdout_rows = [(style.name, measure(style)) for style in HELD_OUT_STYLES]

    def append_table(lines: list[str], rows: list[tuple[str, dict[str, float]]]) -> None:
        lines.extend(
            [
                "| Estilo | Precisão cartas | Recall cartas | F1 cartas | Estado exato |",
                "|---|---|---|---|---|",
            ]
        )
        for name, metrics in rows:
            lines.append(
                f"| {name} | {metrics['precisao']:.1f}% | {metrics['recall']:.1f}% "
                f"| {metrics['cartas']:.1f}% | {metrics['estado_exato']:.1f}% |"
            )

    lines = [
        "# Evidência — Visão F1 (reconhecimento de mesa 2D)",
        "",
        f"Reconhecedor por template rodado em **{N} mesas por estilo**, seeds `20000..20079`.",
        "O comparativo usa exatamente as mesmas imagens nos dois perfis. Os cinco estilos",
        "conhecidos fazem parte do banco de produção; Tahoma e Courier ficam retidos como",
        "holdout sintético. Isso mede apenas este gerador e não mede generalização real.",
        "",
        "## Baseline anterior — somente estilo canônico",
        "",
    ]
    append_table(lines, baseline_rows)
    lines += [
        "",
        "## Produção local — banco multiestilo conhecido",
        "",
    ]
    append_table(lines, production_rows)
    lines += [
        "",
        "## Holdout sintético — fontes fora do banco",
        "",
    ]
    append_table(lines, holdout_rows)
    lines += [
        "",
        "O holdout continua vindo do mesmo gerador e serve apenas como teste adversarial",
        "local. O gate externo com screenshots rotulados permanece bloqueante para qualquer",
        "alegação de precisão real ou promoção do F2.",
        "",
        "## Jogadores + posição (assentos + dealer button)",
        "",
        "Contar participantes e derivar a posição do herói (regra oficial) a partir dos",
        "assentos e do botão. A F1 acha por blob de cor nos estilos avaliados (o azulado",
        "do avatar exige dominar o feltro: `b > g + 25`). Se ainda assim um feltro colidir,",
        "ela **ABSTÉM** (0 jogadores) em vez de contar errado — o copiloto cai no nº",
        "informado. Generalização do F2 exige avaliação real separada com gabarito.",
        "",
        "| Estilo | Nº de jogadores | Posição do herói | Absteve |",
        "|---|---|---|---|",
    ]
    for name, m in production_rows:
        lines.append(
            f"| {name} | {m['jogadores']:.0f}% | {m['posicao']:.0f}% | {m['absteve']:.0f}% |"
        )
    lines += [
        "",
        "Imagens de exemplo (gabarito × detectado) salvas nesta pasta.",
    ]
    (out / "RELATORIO.md").write_text("\n".join(lines), encoding="utf-8")
    receipt = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "scope": "synthetic_f1_only_not_real_world_generalization",
        "n_per_style": N,
        "seeds": [20000, 20000 + N - 1],
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "baseline_canonical_only": dict(baseline_rows),
        "production_known_style_bank": dict(production_rows),
        "synthetic_holdout_not_calibrated": dict(holdout_rows),
    }
    (out / "metrics.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for st in (*STYLES, *HELD_OUT_STYLES):
        save_example(st, 20000, out)

    print("\n".join(lines))
    print(f"\n>>> evidência salva em {out}")


if __name__ == "__main__":
    main()
