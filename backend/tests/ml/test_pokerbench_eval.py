from __future__ import annotations

import hashlib

import pytest

from poker_arena.ml.pokerbench_eval import evaluate_pokerbench_csv


def _csv(tmp_path):
    path = tmp_path / "pokerbench.csv"
    path.write_text(
        ",prev_line,hero_pos,hero_holding,correct_decision,num_players,num_bets,available_moves,pot_size\n"
        "0,UTG/2.0bb/BTN/call/SB/13.0bb/BB/allin,SB,KdKc,call,4,3,\"['call', 'fold']\",117.0\n",
        encoding="utf-8",
    )
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_solver_label_metrics_are_derived_from_the_bound_csv(tmp_path):
    path, digest = _csv(tmp_path)
    result = evaluate_pokerbench_csv(
        path,
        expected_sha256=digest,
        predictor=lambda _encoded: [0.0, 1.0, *([0.0] * 8)],
    )
    assert result.rows == result.eligible == 1
    assert result.parse_failures == result.ambiguous_sizing == 0
    assert result.modal_accuracy == result.top3_accuracy == 1.0
    assert result.modal_accuracy_wilson95[0] < 1.0


def test_dataset_digest_and_probability_contract_fail_closed(tmp_path):
    path, digest = _csv(tmp_path)
    with pytest.raises(ValueError, match="digest mismatch"):
        evaluate_pokerbench_csv(
            path,
            expected_sha256="0" * 64,
            predictor=lambda _encoded: [0.1] * 10,
        )
    with pytest.raises(ValueError, match="not normalized"):
        evaluate_pokerbench_csv(
            path,
            expected_sha256=digest,
            predictor=lambda _encoded: [0.0] * 10,
        )
