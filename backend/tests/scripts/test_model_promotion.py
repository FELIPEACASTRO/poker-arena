from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.promote_model import (
    PromotionRejected,
    build_promoted_manifest,
    write_manifest_proposal,
)
from tests.helpers.model_manifest import promotion_evidence_fixture, verified_test_governance


def _candidate(path: Path) -> Path:
    entry = {
        "path": path.name,
        "state": "candidate",
        "installed": True,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "governance": verified_test_governance(),
        "inputs": [{"name": "images", "dtype": "float32", "shape": [1, 3, 640, 640]}],
        "outputs": [{"name": "output0", "dtype": "float32", "shape": [1, 58, 8400]}],
        "classes": [f"card-{index}" for index in range(54)],
    }
    manifest = path.parent / "MANIFEST.candidate.json"
    manifest.write_text(json.dumps({"schema_version": 1, "artifacts": [entry]}), encoding="utf-8")
    return manifest


def test_pass_receipt_creates_reviewable_proposal_without_mutating_candidate(tmp_path: Path) -> None:
    artifact = tmp_path / "vision.onnx"
    artifact.write_bytes(b"candidate-model")
    candidate = _candidate(artifact)
    evidence = promotion_evidence_fixture(artifact)

    proposal = build_promoted_manifest(
        artifact_path=artifact,
        manifest_path=candidate,
        receipt_path=tmp_path / evidence["path"],
    )

    assert json.loads(candidate.read_text(encoding="utf-8"))["artifacts"][0]["state"] == "candidate"
    promoted = proposal["artifacts"][0]
    assert promoted["state"] == "promoted"
    assert promoted["promotion_receipt"]["sha256"] == evidence["sha256"]
    output = tmp_path / "MANIFEST.promoted.json"
    digest = write_manifest_proposal(output, proposal)
    assert digest == hashlib.sha256(output.read_bytes()).hexdigest()
    with pytest.raises(PromotionRejected, match="already exists"):
        write_manifest_proposal(output, proposal)


def test_receipt_for_another_artifact_is_rejected(tmp_path: Path) -> None:
    artifact = tmp_path / "vision.onnx"
    artifact.write_bytes(b"candidate-model")
    candidate = _candidate(artifact)
    other = tmp_path / "other.onnx"
    other.write_bytes(b"other-model")
    evidence = promotion_evidence_fixture(other)

    with pytest.raises(PromotionRejected, match="did not pass"):
        build_promoted_manifest(
            artifact_path=artifact,
            manifest_path=candidate,
            receipt_path=tmp_path / evidence["path"],
        )
