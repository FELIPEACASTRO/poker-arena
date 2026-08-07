from __future__ import annotations

import json

import pytest
from PIL import Image

from poker_arena.vision.recognize import RecognizedState
from scripts import real_eval, vision_evidence, vlm_eval, warmup_check


def test_real_eval_discovers_images_recursively(tmp_path):
    nested = tmp_path / "client_a" / "session_1"
    nested.mkdir(parents=True)
    Image.new("RGB", (8, 8)).save(nested / "table.PNG")
    Image.new("RGB", (8, 8)).save(tmp_path / "root.jpg")
    (nested / "ignore.txt").write_text("x", encoding="utf-8")

    found = real_eval.discover_images(tmp_path)
    assert found == sorted([nested / "table.PNG", tmp_path / "root.jpg"])


def test_real_eval_loads_sidecar_truth_and_scores_exact_state(tmp_path):
    image = tmp_path / "table.png"
    Image.new("RGB", (8, 8)).save(image)
    truth = {
        "hole": ["As", "Kd"],
        "board": ["2h", "6c", "Tc"],
        "pot": 700,
        "n_players": 6,
        "position": "BTN",
    }
    image.with_suffix(".json").write_text(json.dumps(truth), encoding="utf-8")
    loaded = real_eval.load_truth(image)
    assert loaded == truth

    state = RecognizedState(
        hole=["Kd", "As"],
        board=truth["board"],
        pot=700,
        n_cards=5,
        confidence=0.99,
        n_players=6,
        position="BTN",
    )
    score = real_eval.score_truth(state, loaded)
    assert score["exact_state"] is True
    state.pot = 701
    assert real_eval.score_truth(state, loaded)["exact_state"] is False


def test_real_eval_rejects_incomplete_truth(tmp_path):
    image = tmp_path / "table.png"
    Image.new("RGB", (8, 8)).save(image)
    image.with_suffix(".json").write_text('{"hole":["As","Kd"]}', encoding="utf-8")
    try:
        real_eval.load_truth(image)
    except ValueError as exc:
        assert all(field in str(exc) for field in ("board", "pot", "n_players", "position"))
    else:
        raise AssertionError("incomplete truth must not count as evidence")


def test_real_eval_quality_gate_fails_on_inexact_or_slow_f2():
    evaluations = [
        {
            "truth": {"hole": ["As", "Kd"], "board": [], "pot": 10},
            "scores": {"f2": {"exact_state": False}},
            "elapsed": 4.2,
        }
    ]
    ok, reasons = real_eval.quality_gate(evaluations)
    assert ok is False
    assert any("exact-state" in reason for reason in reasons)
    assert any("lat" in reason.lower() for reason in reasons)


def test_real_eval_quality_gate_requires_production_acceptance():
    evaluations = [
        {
            "truth": {"hole": ["As", "Kd"], "board": [], "pot": 10},
            "scores": {"f2": {"exact_state": True}},
            "acceptance": {"f2": False},
            "elapsed": 0.2,
        }
    ]

    ok, reasons = real_eval.quality_gate(evaluations)
    assert ok is False
    assert any("gate estrito" in reason for reason in reasons)


def test_real_eval_rejects_ten_player_truth(tmp_path):
    image = tmp_path / "table.png"
    Image.new("RGB", (8, 8)).save(image)
    image.with_suffix(".json").write_text(
        json.dumps(
            {
                "hole": ["As", "Kd"],
                "board": [],
                "pot": 10,
                "n_players": 10,
                "position": "BTN",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="2 to 9"):
        real_eval.load_truth(image)


def test_vlm_truth_requires_complete_strategic_context(tmp_path):
    image = tmp_path / "table.png"
    Image.new("RGB", (8, 8)).save(image)
    image.with_suffix(".json").write_text(
        json.dumps({"hole": ["As", "Kd"], "board": [], "pot": 10}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="n_players, position"):
        vlm_eval.load_truth(image)


def test_vlm_eval_card_metrics_penalize_duplicates_and_false_positives():
    counts = vlm_eval.card_detection_counts(["As", "Kd"], ["As", "As", "Qh"])
    assert counts == {"tp": 1, "truth": 2, "pred": 3}


def test_vlm_eval_gate_never_counts_failed_or_unlabelled_samples_as_success():
    code, reasons = vlm_eval.evidence_gate(
        [
            {
                "success": False,
                "truth": {"hole": ["As", "Kd"], "board": [], "pot": 10},
                "elapsed": 0.01,
            },
            {"success": True, "truth": None, "elapsed": 0.01},
        ]
    )

    assert code == 2
    assert any("falhou" in reason for reason in reasons)
    assert any("gabarito ausente" in reason for reason in reasons)


def test_vlm_eval_gate_passes_only_complete_exact_timely_raw_extraction():
    valid = {
        "success": True,
        "truth": {"hole": ["As", "Kd"], "board": [], "pot": 10},
        "score": {"exact_state": True},
        "structural_ok": True,
        "production_authorized": False,
        "elapsed": 0.2,
    }
    assert vlm_eval.evidence_gate([valid]) == (0, [])

    code, reasons = vlm_eval.evidence_gate([{**valid, "elapsed": 4.1}])
    assert code == 1
    assert any("latência" in reason for reason in reasons)


def test_warmup_reports_f2_runtime_failure_instead_of_labelling_fallback_as_f2(monkeypatch):
    monkeypatch.setattr(warmup_check, "vision_model_available", lambda: True)
    monkeypatch.setattr(
        warmup_check,
        "recognize_table_onnx",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("incompatible runtime")),
    )
    fallback_state = object()
    monkeypatch.setattr(warmup_check, "recognize_table", lambda *_args, **_kwargs: fallback_state)

    result = warmup_check._read(Image.new("RGB", (8, 8)))
    assert result.state is fallback_state
    assert result.engine == "F1-template-fallback"
    assert isinstance(result.f2_error, RuntimeError)


def test_card_metrics_penalize_false_positives_and_duplicates():
    counts = vision_evidence.card_detection_counts(["As", "Kd"], ["As", "As"])
    assert counts == {"tp": 1, "truth": 2, "pred": 2}


def test_vision_evidence_exact_state_includes_pot():
    truth = {
        "hole": ["As", "Kd"],
        "board": ["2h", "6c", "Tc"],
        "pot": 700,
        "n_players": 6,
        "position": "BTN",
    }
    state = RecognizedState(
        hole=["Kd", "As"], board=truth["board"], pot=699, n_players=6, position="BTN"
    )
    assert not vision_evidence.is_exact_state(state, truth)
