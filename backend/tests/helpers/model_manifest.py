from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from poker_arena.ml import expert_benchmark, expert_validation, external_validation
from poker_arena.ml.action_space_v2 import REVISION as ACTION_SPACE_V2_REVISION
from poker_arena.ml.encoder_v2 import REVISION as ENCODER_V2_REVISION
from poker_arena.ml.promotion_contract import promotion_contract_sha256


def training_evidence_fixture(path: Path, supported: list[int]) -> dict[str, str]:
    source_binding = "a" * 64
    counts = [100 if index in supported else 0 for index in range(10)]
    trace_path = path.with_name(f"{path.stem}.training_trace.jsonl")
    metrics_path = path.with_name(f"{path.stem}.training_metrics.json")
    trace_path.write_text(
        "\n".join(
            (
                json.dumps(
                    {
                        "event": "training_configuration",
                        "source_binding": source_binding,
                    }
                ),
                json.dumps(
                    {
                        "event": "dataset_prepared",
                        "optimization_training_class_counts": counts,
                    }
                ),
            )
        )
        + "\n",
        encoding="utf-8",
    )
    metrics_path.write_text(
        json.dumps(
            {
                "artifact_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "source_binding": source_binding,
            }
        ),
        encoding="utf-8",
    )
    return {
        "metrics_path": metrics_path.name,
        "metrics_sha256": hashlib.sha256(metrics_path.read_bytes()).hexdigest(),
        "trace_path": trace_path.name,
        "trace_sha256": hashlib.sha256(trace_path.read_bytes()).hexdigest(),
    }


def promotion_evidence_fixture(
    path: Path, artifact_entry: dict[str, Any] | None = None
) -> dict[str, str]:
    """Create a structurally valid pass receipt for isolated runtime-gate tests."""

    artifact_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    total = 360
    sessions = external_validation.MIN_SESSIONS
    exact_lower = external_validation._wilson(total, total, upper=False)
    session_lower = external_validation._wilson(sessions, sessions, upper=False)
    false_accept_upper = external_validation._wilson(0, total, upper=True)
    subgroup_values = {
        "source": [f"source-{index}" for index in range(3)],
        "client": [f"client-{index}" for index in range(3)],
        "theme": [f"theme-{index}" for index in range(2)],
        "deck": [f"deck-{index}" for index in range(2)],
        "resolution": [f"resolution-{index}" for index in range(3)],
        **{
            field: sorted(values)
            for field, values in external_validation._CONTEXT_SUBGROUP_VALUES.items()
        },
    }
    subgroups = []
    for field, values in subgroup_values.items():
        count = total // len(values)
        assert count * len(values) == total
        subgroups.extend(
            {
                "field": field,
                "value_ref": external_validation._safe_group_ref(value),
                "count": count,
                "exact_state": 1.0,
                "exact_state_wilson95_lower": external_validation._wilson(
                    count, count, upper=False
                ),
            }
            for value in values
        )
    contract_sha256 = promotion_contract_sha256(
        artifact_entry or {"path": path.name, "installed": True, "sha256": artifact_sha256}
    )
    receipt = {
        "schema_version": external_validation.SCHEMA_VERSION,
        "profile_revision": external_validation.PROFILE_REVISION,
        "decision": "pass",
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "artifact_sha256": artifact_sha256,
        "artifact_contract_sha256": contract_sha256,
        "dataset_manifest_sha256": "1" * 64,
        "observations_sha256": "2" * 64,
        "pipeline": external_validation.current_pipeline_binding(),
        "execution_environment": external_validation.execution_environment(),
        "policy": dict(external_validation._POLICY),
        "counts": {
            "total": total,
            "accepted": total,
            "clients": 3,
            "themes": 2,
            "decks": 2,
            "sources": 3,
            "sessions": external_validation.MIN_SESSIONS,
            "resolutions": 3,
        },
        "metrics": {
            "exact_state": 1.0,
            "exact_state_wilson95_lower": exact_lower,
            "session_exact_rate": 1.0,
            "session_exact_wilson95_lower": session_lower,
            "coverage": 1.0,
            "false_accept_rate": 0.0,
            "false_accept_wilson95_upper": false_accept_upper,
            "ece_10_bin": 0.0,
            "brier": 0.0,
            "latency_p95_ms": 10.0,
        },
        "subgroups": subgroups,
        "failures": [],
    }
    receipt_path = path.parent / f"{path.stem}.promotion-receipt.json"
    payload = (
        json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    ).encode()
    if receipt_path.exists() and receipt_path.read_bytes() != payload:
        receipt_path.unlink()
    digest = (
        hashlib.sha256(payload).hexdigest()
        if receipt_path.exists()
        else external_validation.write_receipt(receipt_path, receipt)
    )
    return {
        "path": receipt_path.name,
        "sha256": digest,
        "profile_revision": external_validation.PROFILE_REVISION,
        "artifact_contract_sha256": contract_sha256,
    }


def verified_test_governance() -> dict[str, Any]:
    return {
        "license": {
            "status": "verified",
            "id": "LicenseRef-Test-Fixture",
            "reference": "urn:poker-arena:test:license-fixture",
        },
        "lineage": {
            "status": "verified",
            "id": "test-fixture",
            "reference": "urn:poker-arena:test:model-fixture",
        },
    }


def expert_promotion_evidence_fixture(
    path: Path,
    artifact_entry: dict[str, Any],
    *,
    candidate_manifest_sha256: str = "6" * 64,
) -> dict[str, str]:
    """Create a policy-complete Expert receipt for isolated gate tests only."""

    artifact_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    contract_sha256 = promotion_contract_sha256(artifact_entry)
    execution = {
        "candidate_artifact_sha256": artifact_sha256,
        "candidate_manifest_sha256": candidate_manifest_sha256,
        "candidate_contract_sha256": contract_sha256,
        "baseline_policy_sha256": "7" * 64,
        "decision_rule": artifact_entry.get("inference_policy", {}).get("decision_rule", "sampled"),
        **expert_benchmark.current_execution_binding(),
        "binding_sha256": "0" * 64,
    }
    execution["binding_sha256"] = expert_benchmark.execution_binding_sha256(execution)
    raw_cells = []
    for cell in expert_benchmark.preregistered_cells():
        blocks = []
        for index in range(expert_benchmark.MIN_BLOCKS_PER_CELL):
            hands = expert_benchmark.balanced_hands_per_block(
                expert_benchmark.MIN_HANDS_PER_BLOCK,
                cell.table_size,
            )
            block = {
                "id": "0" * 64,
                "deal_seed": index,
                "candidate_policy_seed": index + 10_000,
                "baseline_policy_seed": index + 20_000,
                "hands": hands,
                "candidate_chips_delta": 2 * hands,
                "baseline_chips_delta": 0,
                "big_blind": 20,
                "decisions": 2 * hands,
                "candidate_decisions": hands,
                "baseline_decisions": hands,
                "candidate_action_counts": {
                    action: hands if action == "check" else 0
                    for action in expert_benchmark.ACTION_COUNT_KEYS
                },
                "baseline_action_counts": {
                    action: hands if action == "check" else 0
                    for action in expert_benchmark.ACTION_COUNT_KEYS
                },
                "illegal_actions": 0,
                "non_finite_outputs": 0,
                "fallbacks": 0,
                "execution_binding_sha256": execution["binding_sha256"],
                "candidate_transcript_sha256": hashlib.sha256(
                    f"candidate:{cell.identifier}:{index}".encode()
                ).hexdigest(),
                "baseline_transcript_sha256": hashlib.sha256(
                    f"baseline:{cell.identifier}:{index}".encode()
                ).hexdigest(),
            }
            block["id"] = expert_benchmark._block_identity(cell, block)
            blocks.append(block)
        raw_cells.append(
            {
                "level": cell.level,
                "opponent": cell.opponent,
                "table_size": cell.table_size,
                "stack_depth_bb": cell.stack_depth_bb,
                "blocks": blocks,
            }
        )
    raw_results = {
        "schema_version": 1,
        "profile_revision": expert_benchmark.RAW_RESULTS_PROFILE_REVISION,
        "execution": execution,
        "cells": raw_cells,
    }
    raw_path = path.parent / f"{path.stem}.expert-raw-results.json"
    raw_payload = json.dumps(
        raw_results, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    raw_path.write_bytes(raw_payload)
    raw_sha256 = hashlib.sha256(raw_payload).hexdigest()
    raw_summary = expert_benchmark.summarize_raw_results(raw_results)
    pipeline_binding = expert_validation.current_expert_pipeline_binding()
    dataset_receipt = {
        "schema_version": 1,
        "profile_revision": expert_validation.DATASET_PROFILE_REVISION,
        "dataset_id": "synthetic-unit-test-only",
        "version": "1",
        "license_spdx": "LicenseRef-Test-Fixture",
        "source": "urn:poker-arena:test:synthetic-dataset",
        "content_sha256": "5" * 64,
        "split_receipt_sha256": "6" * 64,
        "permitted_use": ["train-expert-v2"],
    }
    dataset_path = path.parent / f"{path.stem}.expert-dataset-receipt.json"
    dataset_payload = json.dumps(
        dataset_receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    dataset_path.write_bytes(dataset_payload)
    dataset_sha256 = hashlib.sha256(dataset_payload).hexdigest()
    training_receipt = {
        "schema_version": 1,
        "profile_revision": expert_validation.TRAINING_PROFILE_REVISION,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "artifact_sha256": artifact_sha256,
        "artifact_contract_sha256": contract_sha256,
        "encoder_revision": ENCODER_V2_REVISION,
        "action_space_revision": ACTION_SPACE_V2_REVISION,
        "pipeline": pipeline_binding,
        "dataset": {"path": dataset_path.name, "sha256": dataset_sha256},
        "algorithm": {
            "name": "synthetic-unit-test-only",
            "framework": "pytest",
            "framework_version": "1",
            "seeds": [1, 2, 3],
            "steps": 1,
            "examples": 1,
        },
    }
    training_path = path.parent / f"{path.stem}.expert-training-receipt.json"
    training_payload = json.dumps(
        training_receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    training_path.write_bytes(training_payload)
    training_sha256 = hashlib.sha256(training_payload).hexdigest()
    receipt = {
        "schema_version": expert_validation.SCHEMA_VERSION,
        "profile_revision": expert_validation.PROFILE_REVISION,
        "decision": "pass",
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "artifact_sha256": artifact_sha256,
        "artifact_contract_sha256": contract_sha256,
        "pipeline": {
            "git_commit": pipeline_binding["git_commit"],
            "source_receipt_sha256": pipeline_binding["source_receipt_sha256"],
            "dependency_lock_sha256": pipeline_binding["dependency_lock_sha256"],
            "training_receipt_sha256": training_sha256,
            "raw_results_sha256": raw_sha256,
        },
        "protocol": {
            "levels": ["beginner", "intermediate", "advanced"],
            "table_sizes": [2, 6, 9],
            "stack_depths_bb": [20, 50, 100, 200],
            "seat_rotation": "all-seats",
            "duplicate_deals": True,
            "minimum_blocks_per_cell": expert_validation.MIN_BLOCKS_PER_CELL,
            "alpha": 0.05,
            "multiplicity": "holm",
            "decision_rule": artifact_entry.get("inference_policy", {}).get(
                "decision_rule", "sampled"
            ),
        },
        "counts": {
            "hands": raw_summary.hands,
            "decisions": raw_summary.decisions,
            "blocks": raw_summary.blocks,
            "illegal_actions": 0,
            "non_finite_outputs": 0,
            "fallbacks": 0,
        },
        "metrics": {
            "onnx_max_abs_error": 0.0,
            "aggregate_delta_bb100": {
                "estimate": raw_summary.aggregate[0],
                "simultaneous_ci95": list(raw_summary.aggregate[1:]),
            },
            "worst_opponent_delta_bb100": {
                "estimate": raw_summary.worst_cell[0],
                "simultaneous_ci95": list(raw_summary.worst_cell[1:]),
            },
            "max_ci_half_width_bb100": raw_summary.max_ci_half_width,
            "max_holm_adjusted_p_value": raw_summary.max_holm_adjusted_p_value,
        },
        "invariants": {field: True for field in expert_validation._INVARIANT_FIELDS},
        "raw_results": {"path": raw_path.name, "sha256": raw_sha256},
        "training_evidence": {"path": training_path.name, "sha256": training_sha256},
    }
    receipt_path = path.parent / f"{path.stem}.expert-promotion-receipt.json"
    payload = json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    receipt_path.write_bytes(payload)
    return {
        "path": receipt_path.name,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "profile_revision": expert_validation.PROFILE_REVISION,
        "artifact_contract_sha256": contract_sha256,
    }


def write_manifest(path: Path, entry: dict[str, Any]) -> Path:
    manifest = path.parent / "MANIFEST.json"
    manifest.write_text(
        json.dumps({"schema_version": 1, "artifacts": [entry]}),
        encoding="utf-8",
    )
    return manifest


def approve_expert(
    path: Path,
    *,
    state: str = "promoted",
    inference_policy: dict[str, object] | None = None,
) -> Path:
    entry: dict[str, Any] = {
        "path": path.name,
        "state": state,
        "installed": True,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
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
    }
    policy = {
        "decision_rule": "sampled",
        "temperature": 1.0,
        "min_prob_ratio": 0.0,
        "sizing_jitter": 0.0,
        "supported_action_indices": list(range(10)),
        **(inference_policy or {}),
    }
    entry["inference_policy"] = {"state": "approved", **policy}
    supported = list(entry["inference_policy"]["supported_action_indices"])
    entry["training_evidence"] = training_evidence_fixture(path, supported)
    if state == "promoted":
        entry["promotion_receipt"] = expert_promotion_evidence_fixture(path, entry)
    return write_manifest(path, entry)


def approve_vision(path: Path, output_shape: list[int], classes: list[str]) -> Path:
    entry = {
        "path": path.name,
        "state": "approved",
        "installed": True,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "governance": verified_test_governance(),
        "inputs": [{"name": "images", "dtype": "float32", "shape": [1, 3, 640, 640]}],
        "outputs": [{"name": "output0", "dtype": "float32", "shape": output_shape}],
        "classes": classes,
    }
    entry["promotion_receipt"] = promotion_evidence_fixture(path, entry)
    return write_manifest(path, entry)


def approve_card_reader(path: Path) -> Path:
    return write_manifest(
        path,
        {
            "path": path.name,
            "state": "approved",
            "installed": True,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "governance": verified_test_governance(),
            "inputs": [{"name": "images", "dtype": "float32", "shape": [1, 3, 96, 64]}],
            "outputs": [
                {"name": "rank", "dtype": "float32", "shape": [1, 13]},
                {"name": "suit", "dtype": "float32", "shape": [1, 4]},
            ],
        },
    )
