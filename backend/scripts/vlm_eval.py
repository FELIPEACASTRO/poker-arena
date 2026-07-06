"""Avalia o leitor F3-VLM em SCREENSHOTS REAIS — o teste que fecha o gap sim->real.

Roda o Qwen3-VL (ou outro VLM OpenAI-compatível em POKER_VLM_URL) numa pasta de telas
reais e reporta, por imagem: o que o VLM LEU (hole/board/pote/jogadores/posição), se o
sanity-check ACEITA ou ABSTÉM, e a LATÊNCIA end-to-end vs o orçamento de 4s da banca.

É a régua honesta: prova (ou não) que o VLM lê UIs reais inéditas — onde o F2 leu lixo — e
MEDE a latência antes de prometer <=4s. Se tiver o gabarito num .json ao lado (mesmo nome),
também compara e mede acurácia de cartas.

Pré-requisito: subir o modelo e apontar o backend pra ele, ex.:
    llama-server -hf unsloth/Qwen3-VL-4B-Instruct-GGUF:Q4_K_M --mmproj <mmproj.gguf> --port 8080
    set POKER_VLM_URL=http://localhost:8080/v1/chat/completions
Uso: uv run python scripts/vlm_eval.py [pasta_de_imagens]
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from PIL import Image

from poker_arena.vision import check_state, read_table_vlm, vlm_available

_BUDGET_S = 4.0


def _load_truth(img_path: Path) -> dict | None:
    j = img_path.with_suffix(".json")
    if j.exists():
        try:
            return json.loads(j.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None
    return None


def _cards_acc(read: list[str], truth: list[str]) -> str:
    if not truth:
        return "—"
    hit = sum(1 for c in truth if c in read)
    return f"{hit}/{len(truth)}"


def evaluate(path: Path) -> None:
    img = Image.open(path).convert("RGB")
    print(f"\n{'=' * 70}\nTELA REAL: {path.name}  ({img.width}x{img.height})")
    t0 = time.time()
    try:
        st = read_table_vlm(img)
    except Exception as e:  # noqa: BLE001
        print(f"  [VLM] falhou: {type(e).__name__}: {e}")
        return
    dt = time.time() - t0
    san = check_state(st)
    tag = "OK <=4s" if dt <= _BUDGET_S else "ESTOUROU 4s"
    verdict = "ACEITA" if san.ok else "ABSTÉM: " + "; ".join(san.problems)
    print(f"  [VLM] hole={st.hole} board={st.board} pote={st.pot} "
          f"jogadores={st.n_players} pos={st.position!r}")
    print(f"        stacks={st.stacks} | sanity={verdict}")
    print(f"  [LATÊNCIA] {dt:.2f}s  [{tag}]")
    truth = _load_truth(path)
    if truth:
        pot_truth = truth.get("pot")
        pote = "ok" if st.pot == pot_truth else f"{st.pot} vs {pot_truth}"
        print(f"  [ACURÁCIA] hole {_cards_acc(st.hole, truth.get('hole', []))} "
              f"| board {_cards_acc(st.board, truth.get('board', []))} "
              f"| pote {pote}")


def main() -> None:
    if not vlm_available():
        print("POKER_VLM_URL não configurado. Suba o llama-server com o Qwen3-VL e exporte a var.")
        print("  ex.: set POKER_VLM_URL=http://localhost:8080/v1/chat/completions")
        return
    default = Path(__file__).parent / "real_eval" / "imgs"
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else default
    imgs = sorted(p for p in folder.glob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg"))
    if not imgs:
        print(f"sem imagens em {folder}")
        return
    endpoint = os.environ.get("POKER_VLM_URL")
    print(f"# Leitor F3-VLM em {len(imgs)} TELAS REAIS (endpoint {endpoint})")
    lat: list[float] = []
    for p in imgs:
        t0 = time.time()
        evaluate(p)
        lat.append(time.time() - t0)
    if lat:
        n_ok = sum(1 for x in lat if x <= _BUDGET_S)
        print(f"\n{'=' * 70}\nRESUMO: {len(lat)} telas | dentro de 4s: {n_ok}/{len(lat)} | "
              f"latência média {sum(lat) / len(lat):.2f}s  máx {max(lat):.2f}s")


if __name__ == "__main__":
    main()
