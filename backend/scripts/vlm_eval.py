"""Fail-closed evaluation of the uncalibrated remote VLM on authorized screenshots.

Every image must have an adjacent ``.truth.json`` or ``.json`` sidecar for an evidence
gate.  Successful JSON syntax is never treated as calibration: this command measures raw
field extraction and latency, while production remains in abstention until a separate,
independent calibration receipt exists.

Usage: ``uv run python scripts/vlm_eval.py --consent-authorized [image_folder]``.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import time
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image

from poker_arena.position_rules import position_is_compatible
from poker_arena.vision import (
    VlmRequestContext,
    check_state,
    configured_redaction_policy,
    read_table_vlm,
    redact_configured_regions,
    vlm_available,
)
from poker_arena.vision.recognize import RecognizedState
from poker_arena.vision.synth import RANKS, SUITS

_BUDGET_S = 4.0
_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg"})
_VALID_CARDS = frozenset(rank + suit for rank in RANKS for suit in SUITS)
_VALID_POSITIONS = frozenset({"BTN", "SB", "BB", "UTG", "UTG+1", "MP", "LJ", "HJ", "CO"})
_MAX_CHIPS = 999_999_999


def discover_images(folder: Path) -> list[Path]:
    """Discover supported files recursively and deterministically."""

    return sorted(
        path
        for path in folder.rglob("*")
        if path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES
    )


def _validate_truth(data: Any, path: Path) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError(f"truth {path} deve ser um objeto JSON")
    required = ("hole", "board", "pot", "n_players", "position")
    missing = [field for field in required if field not in data]
    if missing:
        raise ValueError(f"truth {path} sem campos obrigatórios: {', '.join(missing)}")
    hole, board, pot = data["hole"], data["board"], data["pot"]
    if not isinstance(hole, list) or len(hole) != 2:
        raise ValueError(f"truth {path}: hole deve conter exatamente 2 cartas")
    if not isinstance(board, list) or len(board) not in (0, 3, 4, 5):
        raise ValueError(f"truth {path}: board deve conter 0/3/4/5 cartas")
    cards = hole + board
    if any(not isinstance(card, str) or card not in _VALID_CARDS for card in cards):
        raise ValueError(f"truth {path}: carta inválida")
    if len(set(cards)) != len(cards):
        raise ValueError(f"truth {path}: carta repetida")
    if isinstance(pot, bool) or not isinstance(pot, int) or not 0 <= pot <= _MAX_CHIPS:
        raise ValueError(f"truth {path}: pot deve ser inteiro entre 0 e {_MAX_CHIPS}")
    if (
        isinstance(data["n_players"], bool)
        or not isinstance(data["n_players"], int)
        or not 2 <= data["n_players"] <= 9
    ):
        raise ValueError(f"truth {path}: n_players deve ser inteiro de 2 a 9")
    if data["position"] not in _VALID_POSITIONS:
        raise ValueError(f"truth {path}: position não pertence à taxonomia canônica")
    if not position_is_compatible(data["position"], data["n_players"]):
        raise ValueError(f"truth {path}: position impossível para n_players")
    return data


def load_truth(image_path: Path) -> dict[str, Any] | None:
    candidates = (
        image_path.with_name(f"{image_path.stem}.truth.json"),
        image_path.with_suffix(".json"),
    )
    truth_path = next((path for path in candidates if path.is_file()), None)
    if truth_path is None:
        return None
    try:
        raw = json.loads(truth_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"sidecar inválido {truth_path}: {exc}") from exc
    return _validate_truth(raw, truth_path)


def card_detection_counts(truth_cards: list[str], predicted_cards: list[str]) -> dict[str, int]:
    """Precision/recall counts in which duplicates and extra predictions are not free."""

    truth_counter = Counter(truth_cards)
    predicted_counter = Counter(predicted_cards)
    return {
        "tp": sum((truth_counter & predicted_counter).values()),
        "truth": len(truth_cards),
        "pred": len(predicted_cards),
    }


def score_truth(state: RecognizedState, truth: dict[str, Any]) -> dict[str, Any]:
    cards = card_detection_counts(truth["hole"] + truth["board"], state.hole + state.board)
    fields: dict[str, bool] = {
        "hole": len(state.hole) == 2 and set(state.hole) == set(truth["hole"]),
        "board": state.board == truth["board"],
        "pot": state.pot == truth["pot"],
    }
    fields["n_players"] = state.n_players == truth["n_players"]
    fields["position"] = state.position == truth["position"]
    return {**fields, **cards, "exact_state": all(fields.values())}


def evaluate(path: Path, context: VlmRequestContext) -> dict[str, Any]:
    """Evaluate one file; failures remain explicit results and never become fast successes."""

    truth = load_truth(path)
    with Image.open(path) as source:
        image = source.convert("RGB")
    print(f"\n{'=' * 70}\nTELA: {path} ({image.width}x{image.height})")
    started = time.perf_counter()
    try:
        state = read_table_vlm(image, context=context)
    except Exception as exc:  # noqa: BLE001 - preserve a failed sample in the receipt
        elapsed = time.perf_counter() - started
        print(f"  [VLM] FALHOU após {elapsed:.2f}s: {type(exc).__name__}: {exc}")
        return {
            "path": path,
            "truth": truth,
            "success": False,
            "elapsed": elapsed,
            "error_type": type(exc).__name__,
        }
    elapsed = time.perf_counter() - started
    structural = check_state(state, min_confidence=0.0)
    production = check_state(state, abstain_below=0.85)
    score = score_truth(state, truth) if truth is not None else None
    latency_tag = "OK" if elapsed <= _BUDGET_S else "ACIMA DO LIMITE"
    print(
        f"  [VLM] hole={state.hole} board={state.board} pot={state.pot} "
        f"jogadores={state.n_players} posição={state.position!r}"
    )
    print(
        f"  [GATES] estrutura={'OK' if structural.ok else 'REPROVADA'}; "
        f"produção={'ERRO: AUTORIZADA' if production.ok else 'ABSTÉM (proposta não calibrada)'}"
    )
    print(f"  [LATÊNCIA] {elapsed:.2f}s [{latency_tag} <= {_BUDGET_S:.0f}s]")
    if score is None:
        print("  [GABARITO] AUSENTE — diagnóstico, não evidência")
    else:
        precision = score["tp"] / score["pred"] if score["pred"] else 0.0
        recall = score["tp"] / score["truth"] if score["truth"] else 0.0
        print(
            f"  [GABARITO] estado_exato={score['exact_state']} "
            f"cartas precisão={precision:.3f} recall={recall:.3f}"
        )
    return {
        "path": path,
        "truth": truth,
        "success": True,
        "elapsed": elapsed,
        "structural_ok": structural.ok,
        "production_authorized": production.ok,
        "score": score,
    }


def evidence_gate(evaluations: list[dict[str, Any]]) -> tuple[int, list[str]]:
    """Return 0 only for complete, exact and timely raw-extraction evidence."""

    reasons: list[str] = []
    if not evaluations:
        return 2, ["nenhuma imagem avaliada"]
    failed = [item for item in evaluations if not item.get("success")]
    if failed:
        reasons.append(f"inferência falhou em {len(failed)}/{len(evaluations)} telas")
    unlabelled = [item for item in evaluations if item.get("truth") is None]
    if unlabelled:
        reasons.append(f"gabarito ausente em {len(unlabelled)}/{len(evaluations)} telas")
    if failed or unlabelled:
        return 2, reasons
    inexact = [item for item in evaluations if not (item.get("score") or {}).get("exact_state")]
    invalid = [item for item in evaluations if item.get("structural_ok") is not True]
    unsafe = [item for item in evaluations if item.get("production_authorized") is not False]
    slow = [item for item in evaluations if float(item["elapsed"]) > _BUDGET_S]
    if inexact:
        reasons.append(f"estado inexato em {len(inexact)}/{len(evaluations)} telas")
    if invalid:
        reasons.append(f"estrutura inválida em {len(invalid)}/{len(evaluations)} telas")
    if unsafe:
        reasons.append(f"abstenção de produção violada em {len(unsafe)}/{len(evaluations)} telas")
    if slow:
        reasons.append(
            f"latência acima de {_BUDGET_S:.0f}s em {len(slow)}/{len(evaluations)} telas"
        )
    return (1, reasons) if reasons else (0, [])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", nargs="?", type=Path)
    parser.add_argument(
        "--consent-authorized",
        action="store_true",
        help="confirma que as imagens são próprias/autorizadas para processamento remoto",
    )
    args = parser.parse_args(argv)
    if not args.consent_authorized:
        parser.error("use --consent-authorized somente para um corpus próprio/autorizado")
    if not vlm_available():
        print("EVIDENCE GATE: INCOMPLETE — lane VLM indisponível ou insegura")
        return 2
    folder = args.folder or Path(__file__).parent / "real_eval" / "imgs"
    images = discover_images(folder)
    if not images:
        print(f"EVIDENCE GATE: INCOMPLETE — sem imagens em {folder}")
        return 2
    endpoint = os.environ.get("POKER_VLM_URL", "")
    print(f"# F3-VLM em {len(images)} telas autorizadas (endpoint {endpoint})")
    context = VlmRequestContext(
        consent=True,
        session_id=f"eval-{secrets.token_hex(24)}",
        redaction_hook=redact_configured_regions,
        redaction_policy=configured_redaction_policy(),
    )
    evaluations: list[dict[str, Any]] = []
    for image in images:
        try:
            evaluations.append(evaluate(image, context))
        except Exception as exc:  # noqa: BLE001 - invalid image/truth is explicit evidence failure
            print(f"\n{image}: ERRO DE EVIDÊNCIA {type(exc).__name__}: {exc}")
            evaluations.append(
                {"path": image, "truth": None, "success": False, "error_type": type(exc).__name__}
            )

    successful = [item for item in evaluations if item.get("success")]
    within_budget = sum(float(item["elapsed"]) <= _BUDGET_S for item in successful)
    exact = sum(bool((item.get("score") or {}).get("exact_state")) for item in successful)
    print(
        f"\nRESUMO: sucesso={len(successful)}/{len(evaluations)}; "
        f"<=4s={within_budget}/{len(successful)}; estado_exato={exact}/{len(successful)}"
    )
    code, reasons = evidence_gate(evaluations)
    if code == 0:
        print("EVIDENCE GATE: PASS — extração bruta; produção continua em abstinência")
    else:
        label = "INCOMPLETE" if code == 2 else "FAIL"
        print(f"EVIDENCE GATE: {label} — {'; '.join(reasons)}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
