from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from poker_arena.ml import external_validation
from poker_arena.ml.promotion_contract import promotion_contract_sha256


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


def write_manifest(path: Path, entry: dict[str, Any]) -> Path:
    manifest = path.parent / "MANIFEST.json"
    manifest.write_text(
        json.dumps({"schema_version": 1, "artifacts": [entry]}),
        encoding="utf-8",
    )
    return manifest


def approve_expert(
    path: Path,
    feature_size: int,
    action_count: int,
    *,
    state: str = "approved",
    inference_policy: dict[str, float] | None = None,
) -> Path:
    entry: dict[str, Any] = {
        "path": path.name,
        "state": state,
        "installed": True,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "governance": verified_test_governance(),
        "inputs": [{"name": "obs", "dtype": "float32", "shape": [1, feature_size]}],
        "outputs": [{"name": "logits", "dtype": "float32", "shape": [1, action_count]}],
    }
    if inference_policy is not None:
        entry["inference_policy"] = {"state": "approved", **inference_policy}
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
