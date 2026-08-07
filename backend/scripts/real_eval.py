"""Evaluate vision on recursively discovered real screenshots with auditable truth.

Each labelled image must have ``<stem>.json`` or ``<stem>.truth.json`` beside it.
A label is evidence only when it includes the complete image-derived state: hole,
board, pot, player count and hero position. Unlabelled screenshots remain useful
diagnostics, but the command exits non-zero if no valid truth exists.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from PIL import Image

from poker_arena.position_rules import position_is_compatible
from poker_arena.vision import (
    check_state,
    recognize_table,
    recognize_table_onnx,
    vision_model_available,
)
from poker_arena.vision.recognize import RecognizedState
from poker_arena.vision.synth import RANKS, SUITS

_BUDGET_S = 4.0
_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg"})
_VALID_CARDS = frozenset(r + s for r in RANKS for s in SUITS)
_VALID_POSITIONS = frozenset({"BTN", "SB", "BB", "UTG", "UTG+1", "MP", "LJ", "HJ", "CO"})


def discover_images(folder: Path) -> list[Path]:
    """Find supported screenshots recursively and deterministically."""
    return sorted(
        path
        for path in folder.rglob("*")
        if path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES
    )


def _validate_truth(data: Any, path: Path) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError(f"truth {path} must be a JSON object")
    required = ("hole", "board", "pot", "n_players", "position")
    missing = [key for key in required if key not in data]
    if missing:
        raise ValueError(f"truth {path} missing required fields: {', '.join(missing)}")
    hole, board, pot = data["hole"], data["board"], data["pot"]
    if not isinstance(hole, list) or len(hole) != 2:
        raise ValueError(f"truth {path}: hole must contain exactly 2 cards")
    if not isinstance(board, list) or len(board) not in (0, 3, 4, 5):
        raise ValueError(f"truth {path}: board must contain 0/3/4/5 cards")
    cards = hole + board
    if any(not isinstance(card, str) or card not in _VALID_CARDS for card in cards):
        raise ValueError(f"truth {path}: invalid card")
    if len(set(cards)) != len(cards):
        raise ValueError(f"truth {path}: duplicate card")
    if isinstance(pot, bool) or not isinstance(pot, int) or pot < 0:
        raise ValueError(f"truth {path}: pot must be a non-negative integer")
    if (
        isinstance(data["n_players"], bool)
        or not isinstance(data["n_players"], int)
        or not 2 <= data["n_players"] <= 9
    ):
        raise ValueError(f"truth {path}: n_players must be an integer from 2 to 9")
    if data["position"] not in _VALID_POSITIONS:
        raise ValueError(f"truth {path}: position must use the canonical taxonomy")
    if not position_is_compatible(data["position"], data["n_players"]):
        raise ValueError(f"truth {path}: position is impossible for n_players")
    return data


def load_truth(image_path: Path) -> dict[str, Any] | None:
    """Load and validate an adjacent truth sidecar, preferring ``.truth.json``."""
    candidates = (
        image_path.with_name(f"{image_path.stem}.truth.json"),
        image_path.with_suffix(".json"),
    )
    truth_path = next((path for path in candidates if path.exists()), None)
    if truth_path is None:
        return None
    try:
        raw = json.loads(truth_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid truth sidecar {truth_path}: {exc}") from exc
    return _validate_truth(raw, truth_path)


def score_truth(state: RecognizedState, truth: dict[str, Any]) -> dict[str, bool]:
    """Score every labelled state field and the conjunction named exact_state."""
    fields = {
        "hole": len(state.hole) == 2 and set(state.hole) == set(truth["hole"]),
        "board": state.board == truth["board"],
        "pot": state.pot == truth["pot"],
    }
    fields["n_players"] = state.n_players == truth["n_players"]
    fields["position"] = state.position == truth["position"]
    fields["exact_state"] = all(fields.values())
    return fields


def quality_gate(evaluations: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    """Fail when production F2 is missing, inexact, or over the latency budget."""
    labelled = [item for item in evaluations if item.get("truth") is not None]
    reasons: list[str] = []
    if not labelled:
        return False, ["nenhuma tela rotulada"]
    f2_scores = [item.get("scores", {}).get("f2") for item in labelled]
    if any(score is None for score in f2_scores):
        reasons.append("F2 ausente/falhou em uma ou mais telas rotuladas")
    exact = sum(bool(score and score.get("exact_state")) for score in f2_scores)
    if exact != len(labelled):
        reasons.append(f"F2 exact-state {exact}/{len(labelled)}")
    accepted = sum(item.get("acceptance", {}).get("f2") is True for item in labelled)
    if accepted != len(labelled):
        reasons.append(f"F2 aceito pelo gate estrito {accepted}/{len(labelled)}")
    slow = sum(float(item.get("elapsed", float("inf"))) > _BUDGET_S for item in labelled)
    if slow:
        reasons.append(f"latência F2 acima de {_BUDGET_S:.0f}s em {slow}/{len(labelled)} telas")
    return not reasons, reasons


def _print_state(label: str, state: RecognizedState, *, sanity=None) -> None:
    sanity = sanity or check_state(state, abstain_below=0.85)
    verdict = "OK" if sanity.ok else "ABSTEM: " + "; ".join(sanity.problems)
    print(
        f"  [{label}] hole={state.hole} board={state.board} "
        f"pote={state.pot}({state.pot_source}) jogadores={state.n_players} "
        f"pos={state.position!r} conf={state.confidence}"
    )
    print(f"               stacks={state.stacks} | sanity={verdict}")


def evaluate_image(path: Path) -> dict[str, Any]:
    img = Image.open(path).convert("RGB")
    truth = load_truth(path)
    print(f"\n{'=' * 70}\nTELA REAL: {path}  ({img.width}x{img.height})")

    results: dict[str, RecognizedState] = {}
    f2_error: Exception | None = None
    t0 = time.perf_counter()
    if vision_model_available():
        try:
            results["f2"] = recognize_table_onnx(img, ocr_numbers=True)
        except Exception as exc:  # noqa: BLE001 - report contract/runtime failure and continue F1
            f2_error = exc
    if "f2" not in results:
        results["f1"] = recognize_table(img, ocr_numbers=True)
    primary = results["f2"] if "f2" in results else results["f1"]
    primary_sanity = check_state(primary, abstain_below=0.85)
    elapsed = time.perf_counter() - t0
    tag = "OK <=4s" if elapsed <= _BUDGET_S else "ESTOUROU o limite de 4s"
    print(f"  [LATENCIA] visao+OCR+sanity: {elapsed:.2f}s [{tag}]")

    if "f1" not in results:
        results["f1"] = recognize_table(img, ocr_numbers=True)
    sanity_by_engine = {
        engine: (primary_sanity if state is primary else check_state(state, abstain_below=0.85))
        for engine, state in results.items()
    }
    _print_state("F1 template", results["f1"], sanity=sanity_by_engine["f1"])

    if vision_model_available():
        if f2_error is None:
            _print_state("F2 treinado", results["f2"], sanity=sanity_by_engine["f2"])
        else:
            print(f"  [F2 treinado] falhou: {type(f2_error).__name__}: {f2_error}")
    else:
        print("  [F2 treinado] MODELO AUSENTE; esta execucao nao prova desempenho F2")

    scores: dict[str, dict[str, bool]] = {}
    if truth is None:
        print("  [GABARITO] AUSENTE - diagnostico somente; nao conta como evidencia")
    else:
        for engine, state in results.items():
            scores[engine] = score_truth(state, truth)
            print(f"  [GABARITO/{engine.upper()}] {scores[engine]}")
    return {
        "path": path,
        "truth": truth,
        "scores": scores,
        "acceptance": {engine: sanity.ok for engine, sanity in sanity_by_engine.items()},
        "elapsed": elapsed,
    }


def main() -> int:
    folder = (
        Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "real_eval" / "imgs"
    )
    images = discover_images(folder)
    if not images:
        print(f"sem imagens em {folder}")
        return 2
    print(f"# Visao em {len(images)} TELAS REAIS (F2 instalado: {vision_model_available()})")
    evaluations = []
    errors = 0
    for path in images:
        try:
            evaluations.append(evaluate_image(path))
        except Exception as exc:  # noqa: BLE001 - keep auditing remaining files
            errors += 1
            print(f"\n{path}: erro {type(exc).__name__}: {exc}")

    labelled = [item for item in evaluations if item["truth"] is not None]
    if not labelled:
        print("\nEVIDENCE GATE: FAIL - nenhum screenshot possui gabarito valido")
        return 2
    for engine in ("f1", "f2"):
        scored = [item["scores"][engine] for item in labelled if engine in item["scores"]]
        if scored:
            exact = sum(score["exact_state"] for score in scored)
            print(f"{engine.upper()} exact-state: {exact}/{len(scored)}")
    f2_scored = sum("f2" in item["scores"] for item in labelled)
    if errors or not vision_model_available() or f2_scored != len(labelled):
        print(
            f"EVIDENCE GATE: INCOMPLETE - erros={errors}, F2_rotulado={f2_scored}/{len(labelled)}"
        )
        return 2
    quality_ok, quality_reasons = quality_gate(evaluations)
    if not quality_ok:
        print("EVIDENCE GATE: FAIL - " + "; ".join(quality_reasons))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
