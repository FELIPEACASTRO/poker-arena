from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from poker_arena.ml import external_validation


def promotion_evidence_fixture(path: Path) -> dict[str, str]:
    """Create a structurally valid pass receipt for isolated runtime-gate tests."""

    artifact_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    receipt = {
        "schema_version": external_validation.SCHEMA_VERSION,
        "profile_revision": external_validation.PROFILE_REVISION,
        "decision": "pass",
        "generated_at": "2026-01-01T00:00:00Z",
        "artifact_sha256": artifact_sha256,
        "dataset_manifest_sha256": "1" * 64,
        "observations_sha256": "2" * 64,
        "pipeline": external_validation.current_pipeline_binding(),
        "execution_environment": external_validation.execution_environment(),
        "policy": dict(external_validation._POLICY),
        "counts": {
            "total": external_validation.MIN_TOTAL,
            "accepted": external_validation.MIN_TOTAL,
            "clients": 3,
            "themes": 2,
            "decks": 2,
            "sources": 3,
            "sessions": 20,
            "resolutions": 3,
        },
        "metrics": {
            "exact_state_wilson95_lower": 0.99,
            "false_accept_wilson95_upper": 0.0,
            "ece_10_bin": 0.0,
            "brier": 0.0,
            "latency_p95_ms": 10.0,
        },
        "subgroups": [
            {
                "field": "client",
                "value_ref": "fixture",
                "count": 200,
                "exact_state": 0.99,
                "exact_state_wilson95_lower": 0.96,
            }
        ],
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
    return write_manifest(
        path,
        {
            "path": path.name,
            "state": "approved",
            "installed": True,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "governance": verified_test_governance(),
            "promotion_receipt": promotion_evidence_fixture(path),
            "inputs": [{"name": "images", "dtype": "float32", "shape": [1, 3, 640, 640]}],
            "outputs": [{"name": "output0", "dtype": "float32", "shape": output_shape}],
            "classes": classes,
        },
    )


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
