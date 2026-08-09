from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import onnxruntime as ort
import pytest
from onnx import TensorProto, checker, helper, save_model

from scripts.promote_model import (
    PromotionRejected,
    build_promoted_manifest,
    write_manifest_proposal,
)
from tests.helpers.expert_onnx import write_constant_expert_v2
from tests.helpers.model_manifest import (
    approve_expert,
    expert_promotion_evidence_fixture,
    promotion_evidence_fixture,
    verified_test_governance,
)


def _write_vision_onnx(path: Path, *, marker: str) -> None:
    inputs = [helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, 640, 640])]
    outputs = [helper.make_tensor_value_info("output0", TensorProto.FLOAT, [1, 58, 8400])]
    output_shape = helper.make_tensor("output_shape", TensorProto.INT64, [3], [1, 58, 8400])
    constant = helper.make_node("ConstantOfShape", ["output_shape"], ["output0"])
    graph = helper.make_graph(
        [constant], "promotion-fixture", inputs, outputs, initializer=[output_shape]
    )
    model = helper.make_model(
        graph,
        opset_imports=[helper.make_opsetid("", 13)],
        ir_version=10,
    )
    metadata = model.metadata_props.add()
    metadata.key = "fixture_marker"
    metadata.value = marker
    checker.check_model(model)
    save_model(model, path)
    session = ort.InferenceSession(path.read_bytes(), providers=["CPUExecutionProvider"])
    assert session.get_outputs()[0].shape == [1, 58, 8400]
    output = session.run(None, {"images": np.zeros((1, 3, 640, 640), dtype=np.float32)})[0]
    assert output.shape == (1, 58, 8400)


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


def test_pass_receipt_creates_reviewable_proposal_without_mutating_candidate(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "vision.onnx"
    _write_vision_onnx(artifact, marker="candidate")
    candidate = _candidate(artifact)
    candidate_entry = json.loads(candidate.read_text(encoding="utf-8"))["artifacts"][0]
    evidence = promotion_evidence_fixture(artifact, candidate_entry)

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
    _write_vision_onnx(artifact, marker="candidate")
    candidate = _candidate(artifact)
    other = tmp_path / "other.onnx"
    _write_vision_onnx(other, marker="other")
    evidence = promotion_evidence_fixture(other)

    with pytest.raises(PromotionRejected, match="did not pass"):
        build_promoted_manifest(
            artifact_path=artifact,
            manifest_path=candidate,
            receipt_path=tmp_path / evidence["path"],
        )


def test_expert_uses_its_own_fail_closed_promotion_profile(tmp_path: Path) -> None:
    artifact = tmp_path / "expert.onnx"
    write_constant_expert_v2(artifact, [0.0] * 10)
    manifest = approve_expert(
        artifact,
        state="candidate",
        inference_policy={
            "decision_rule": "modal",
            "temperature": 0.0,
            "min_prob_ratio": 0.0,
            "sizing_jitter": 0.0,
        },
    )
    entry = json.loads(manifest.read_text(encoding="utf-8"))["artifacts"][0]
    evidence = expert_promotion_evidence_fixture(
        artifact,
        entry,
        candidate_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
    )

    proposal = build_promoted_manifest(
        artifact_path=artifact,
        manifest_path=manifest,
        receipt_path=tmp_path / evidence["path"],
        kind="expert",
    )

    promoted = proposal["artifacts"][0]
    assert promoted["state"] == "promoted"
    assert promoted["promotion_receipt"]["profile_revision"].startswith(
        "poker-arena-expert-promotion-"
    )
