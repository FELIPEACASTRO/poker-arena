from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from poker_arena.ml import expert_benchmark
from poker_arena.ml.action_space_v2 import REVISION as ACTION_SPACE_V2_REVISION
from poker_arena.ml.encoder_v2 import REVISION as ENCODER_V2_REVISION
from poker_arena.ml.expert_validation import (
    ExpertPromotionEvidenceError,
    verify_expert_promotion_receipt,
)
from poker_arena.ml.promotion_contract import promotion_contract_sha256
from tests.helpers.model_manifest import (
    expert_promotion_evidence_fixture,
    verified_test_governance,
)


def _evidence(tmp_path):
    artifact = tmp_path / "expert.onnx"
    artifact.write_bytes(b"expert-fixture")
    entry = {
        "path": artifact.name,
        "state": "promoted",
        "installed": True,
        "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "governance": verified_test_governance(),
        "encoder_revision": ENCODER_V2_REVISION,
        "action_space_revision": ACTION_SPACE_V2_REVISION,
        "inputs": [
            {"name": "cards", "dtype": "float32", "shape": [1, 208]},
            {"name": "global", "dtype": "float32", "shape": [1, 24]},
            {"name": "seats", "dtype": "float32", "shape": [1, 9, 12]},
            {"name": "history", "dtype": "float32", "shape": [1, 15, 26]},
            {"name": "history_mask", "dtype": "float32", "shape": [1, 15]},
            {"name": "legal_mask", "dtype": "float32", "shape": [1, 10]},
        ],
        "outputs": [{"name": "logits", "dtype": "float32", "shape": [1, 10]}],
        "inference_policy": {
            "state": "promoted",
            "decision_rule": "sampled",
            "temperature": 1.0,
            "min_prob_ratio": 0.0,
            "sizing_jitter": 0.0,
        },
    }
    pointer = expert_promotion_evidence_fixture(artifact, entry)
    return artifact, entry, pointer, tmp_path / pointer["path"]


def _verify(artifact, entry, pointer, receipt):
    return verify_expert_promotion_receipt(
        receipt,
        expected_sha256=pointer["sha256"],
        artifact_sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(),
        artifact_contract_sha256=promotion_contract_sha256(entry),
        decision_rule="sampled",
    )


def _rewrite(pointer, receipt, mutate):
    value = json.loads(receipt.read_text(encoding="utf-8"))
    mutate(value)
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    receipt.write_bytes(payload)
    pointer["sha256"] = hashlib.sha256(payload).hexdigest()


def _rewrite_raw(pointer, receipt, mutate, *, refresh_metrics=False):
    value = json.loads(receipt.read_text(encoding="utf-8"))
    raw_path = receipt.parent / value["raw_results"]["path"]
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    mutate(raw)
    binding = raw["execution"]["binding_sha256"]
    for raw_cell in raw["cells"]:
        cell = expert_benchmark.BenchmarkCell(
            raw_cell["level"],
            raw_cell["opponent"],
            raw_cell["table_size"],
            raw_cell["stack_depth_bb"],
        )
        for block in raw_cell["blocks"]:
            block["execution_binding_sha256"] = binding
            block["id"] = expert_benchmark._block_identity(cell, block)
    raw_payload = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    raw_path.write_bytes(raw_payload)
    raw_sha = hashlib.sha256(raw_payload).hexdigest()
    value["raw_results"]["sha256"] = raw_sha
    value["pipeline"]["raw_results_sha256"] = raw_sha
    if refresh_metrics:
        summary = expert_benchmark.summarize_raw_results(raw)
        value["counts"].update(
            {
                "hands": summary.hands,
                "decisions": summary.decisions,
                "blocks": summary.blocks,
                "illegal_actions": summary.illegal_actions,
                "non_finite_outputs": summary.non_finite_outputs,
                "fallbacks": summary.fallbacks,
            }
        )
        value["metrics"].update(
            {
                "aggregate_delta_bb100": {
                    "estimate": summary.aggregate[0],
                    "simultaneous_ci95": list(summary.aggregate[1:]),
                },
                "worst_opponent_delta_bb100": {
                    "estimate": summary.worst_cell[0],
                    "simultaneous_ci95": list(summary.worst_cell[1:]),
                },
                "max_ci_half_width_bb100": summary.max_ci_half_width,
                "max_holm_adjusted_p_value": summary.max_holm_adjusted_p_value,
            }
        )
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    receipt.write_bytes(payload)
    pointer["sha256"] = hashlib.sha256(payload).hexdigest()


def test_valid_expert_receipt_passes_all_exact_gates(tmp_path):
    artifact, entry, pointer, receipt = _evidence(tmp_path)
    verified = _verify(artifact, entry, pointer, receipt)
    assert verified.hands > 0
    assert verified.decisions >= verified.hands


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda value: value["counts"].__setitem__("fallbacks", 1), "counts_below_policy"),
        (
            lambda value: value["metrics"]["aggregate_delta_bb100"].__setitem__(
                "simultaneous_ci95", [-1.0, 19.0]
            ),
            "metrics_not_derived",
        ),
        (
            lambda value: value["invariants"].__setitem__("suit_permutation", False),
            "invariants_failed",
        ),
        (lambda value: value["protocol"].__setitem__("decision_rule", "modal"), "protocol_invalid"),
        (lambda value: value["counts"].__setitem__("hands", 1), "counts_below_policy"),
        (
            lambda value: value["pipeline"].__setitem__("source_receipt_sha256", "0" * 64),
            "pipeline_mismatch",
        ),
        (lambda value: value.__setitem__("undeclared", True), "schema_invalid"),
    ],
)
def test_receipt_rejects_false_pass_mutations(tmp_path, mutate, code):
    artifact, entry, pointer, receipt = _evidence(tmp_path)
    _rewrite(pointer, receipt, mutate)
    with pytest.raises(ExpertPromotionEvidenceError) as rejection:
        _verify(artifact, entry, pointer, receipt)
    assert rejection.value.code == code


def test_receipt_rejects_stale_evidence(tmp_path):
    artifact, entry, pointer, receipt = _evidence(tmp_path)
    stale = (datetime.now(UTC) - timedelta(days=31)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _rewrite(pointer, receipt, lambda value: value.__setitem__("generated_at", stale))
    with pytest.raises(ExpertPromotionEvidenceError) as rejection:
        _verify(artifact, entry, pointer, receipt)
    assert rejection.value.code == "receipt_stale"


def test_receipt_rejects_duplicate_json_keys(tmp_path):
    artifact, entry, pointer, receipt = _evidence(tmp_path)
    payload = (
        receipt.read_text(encoding="utf-8")
        .replace('"schema_version":1', '"schema_version":1,"schema_version":1', 1)
        .encode()
    )
    receipt.write_bytes(payload)
    pointer["sha256"] = hashlib.sha256(payload).hexdigest()
    with pytest.raises(ExpertPromotionEvidenceError) as rejection:
        _verify(artifact, entry, pointer, receipt)
    assert rejection.value.code == "receipt_unreadable"


def test_receipt_requires_the_bound_training_and_dataset_files(tmp_path):
    artifact, entry, pointer, receipt = _evidence(tmp_path)
    value = json.loads(receipt.read_text(encoding="utf-8"))
    training_path = receipt.parent / value["training_evidence"]["path"]
    training = json.loads(training_path.read_text(encoding="utf-8"))
    dataset_path = training_path.parent / training["dataset"]["path"]
    dataset_path.write_bytes(dataset_path.read_bytes() + b" ")

    with pytest.raises(ExpertPromotionEvidenceError) as rejection:
        _verify(artifact, entry, pointer, receipt)
    assert rejection.value.code == "dataset_evidence_invalid"


def test_one_hand_blocks_cannot_masquerade_as_a_powered_panel(tmp_path):
    artifact, entry, pointer, receipt = _evidence(tmp_path)

    def mutate(raw):
        block = raw["cells"][0]["blocks"][0]
        block["hands"] = 1
        block["candidate_chips_delta"] = 2

    _rewrite_raw(pointer, receipt, mutate)
    with pytest.raises(ExpertPromotionEvidenceError) as rejection:
        _verify(artifact, entry, pointer, receipt)
    assert rejection.value.code == "raw_results_invalid"


def test_holm_failed_cells_cannot_pass_on_a_positive_aggregate(tmp_path):
    artifact, entry, pointer, receipt = _evidence(tmp_path)

    def mutate(raw):
        for raw_cell in raw["cells"][:18]:
            for block in raw_cell["blocks"]:
                block["candidate_chips_delta"] = block["baseline_chips_delta"]

    _rewrite_raw(pointer, receipt, mutate, refresh_metrics=True)
    with pytest.raises(ExpertPromotionEvidenceError) as rejection:
        _verify(artifact, entry, pointer, receipt)
    assert rejection.value.code == "metrics_below_policy"


def test_raw_execution_hashes_must_match_the_current_runner(tmp_path):
    artifact, entry, pointer, receipt = _evidence(tmp_path)

    def mutate(raw):
        raw["execution"]["runner_sha256"] = "0" * 64
        raw["execution"]["binding_sha256"] = expert_benchmark.execution_binding_sha256(
            raw["execution"]
        )

    _rewrite_raw(pointer, receipt, mutate, refresh_metrics=True)
    with pytest.raises(ExpertPromotionEvidenceError) as rejection:
        _verify(artifact, entry, pointer, receipt)
    assert rejection.value.code == "raw_execution_mismatch"
