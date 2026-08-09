from __future__ import annotations

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import onnx
import pytest
from onnx import TensorProto, helper

import poker_arena.model_artifacts as model_artifacts
from poker_arena.ml.action_space_v2 import REVISION as ACTION_SPACE_V2_REVISION
from poker_arena.ml.encoder_v2 import REVISION as ENCODER_V2_REVISION
from poker_arena.model_artifacts import (
    ModelArtifactUnavailable,
    clear_model_artifact_cache,
    model_artifact_available,
    revalidate_model_artifact_identity,
    verify_evaluation_candidate,
    verify_model_artifact,
    verify_runtime_contract,
)
from tests.helpers.model_manifest import (
    expert_promotion_evidence_fixture,
    promotion_evidence_fixture,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _isolated_receipt_cache():
    clear_model_artifact_cache()
    yield
    clear_model_artifact_cache()


def _verified_governance() -> dict[str, object]:
    return {
        "license": {
            "status": "verified",
            "id": "Apache-2.0",
            "reference": "https://www.apache.org/licenses/LICENSE-2.0",
        },
        "lineage": {
            "status": "verified",
            "id": "training-run-42",
            "reference": "urn:poker-arena:test:training-run-42",
        },
    }


def _expert_entry(artifact_path: Path, **updates: object) -> dict[str, object]:
    source_binding = "a" * 64
    trace_path = artifact_path.with_name(f"{artifact_path.stem}.training_trace.jsonl")
    metrics_path = artifact_path.with_name(f"{artifact_path.stem}.training_metrics.json")
    trace_path.write_text(
        json.dumps({"event": "training_configuration", "source_binding": source_binding})
        + "\n"
        + json.dumps(
            {"event": "dataset_prepared", "optimization_training_class_counts": [100] * 10}
        )
        + "\n",
        encoding="utf-8",
    )
    metrics_path.write_text(
        json.dumps(
            {
                "artifact_sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
                "source_binding": source_binding,
            }
        ),
        encoding="utf-8",
    )
    entry: dict[str, object] = {
        "path": artifact_path.name,
        "state": "promoted",
        "installed": True,
        "sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
        "governance": _verified_governance(),
        "encoder_revision": ENCODER_V2_REVISION,
        "action_space_revision": ACTION_SPACE_V2_REVISION,
        "inputs": [
            {"name": "cards", "dtype": "float32", "shape": ["batch", 208]},
            {"name": "global", "dtype": "float32", "shape": ["batch", 24]},
            {"name": "seats", "dtype": "float32", "shape": ["batch", 9, 12]},
            {"name": "history", "dtype": "float32", "shape": ["batch", 15, 26]},
            {"name": "history_mask", "dtype": "float32", "shape": ["batch", 15]},
            {"name": "legal_mask", "dtype": "float32", "shape": ["batch", 10]},
        ],
        "outputs": [{"name": "logits", "dtype": "float32", "shape": ["batch", 10]}],
        "inference_policy": {
            "state": "approved",
            "decision_rule": "sampled",
            "temperature": 1.0,
            "min_prob_ratio": 0.0,
            "sizing_jitter": 0.0,
            "supported_action_indices": list(range(10)),
        },
        "training_evidence": {
            "metrics_path": metrics_path.name,
            "metrics_sha256": hashlib.sha256(metrics_path.read_bytes()).hexdigest(),
            "trace_path": trace_path.name,
            "trace_sha256": hashlib.sha256(trace_path.read_bytes()).hexdigest(),
        },
    }
    entry.update(updates)
    declared_path = str(entry["path"])
    if "/" in declared_path:
        prefix = declared_path.rsplit("/", 1)[0]
        evidence = dict(entry["training_evidence"])
        evidence["metrics_path"] = f"{prefix}/{evidence['metrics_path']}"
        evidence["trace_path"] = f"{prefix}/{evidence['trace_path']}"
        entry["training_evidence"] = evidence
    policy = entry.get("inference_policy")
    if isinstance(policy, dict) and isinstance(policy.get("supported_action_indices"), list):
        counts = [100 if index in policy["supported_action_indices"] else 0 for index in range(10)]
        trace_path.write_text(
            json.dumps({"event": "training_configuration", "source_binding": source_binding})
            + "\n"
            + json.dumps(
                {"event": "dataset_prepared", "optimization_training_class_counts": counts}
            )
            + "\n",
            encoding="utf-8",
        )
        evidence = dict(entry["training_evidence"])
        evidence["trace_sha256"] = hashlib.sha256(trace_path.read_bytes()).hexdigest()
        entry["training_evidence"] = evidence
    if entry["state"] == "promoted" and "promotion_receipt" not in entry:
        pointer = expert_promotion_evidence_fixture(artifact_path, entry)
        declared_path = str(entry["path"])
        if "/" in declared_path:
            pointer["path"] = f"{declared_path.rsplit('/', 1)[0]}/{pointer['path']}"
        entry["promotion_receipt"] = pointer
    return entry


def _write_manifest(path: Path, entry: dict[str, object]) -> Path:
    manifest = path.parent / "MANIFEST.json"
    manifest.write_text(json.dumps({"schema_version": 1, "artifacts": [entry]}), encoding="utf-8")
    return manifest


def _write_test_onnx(path: Path, *, usage: str = "expert", marker: str = "base") -> Path:
    if usage == "vision":
        inputs = [helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, 640, 640])]
        outputs = [helper.make_tensor_value_info("output0", TensorProto.FLOAT, [1, 58, 8400])]
    else:
        inputs = [
            helper.make_tensor_value_info("cards", TensorProto.FLOAT, [1, 208]),
            helper.make_tensor_value_info("global", TensorProto.FLOAT, [1, 24]),
            helper.make_tensor_value_info("seats", TensorProto.FLOAT, [1, 9, 12]),
            helper.make_tensor_value_info("history", TensorProto.FLOAT, [1, 15, 26]),
            helper.make_tensor_value_info("history_mask", TensorProto.FLOAT, [1, 15]),
            helper.make_tensor_value_info("legal_mask", TensorProto.FLOAT, [1, 10]),
        ]
        outputs = [helper.make_tensor_value_info("logits", TensorProto.FLOAT, [1, 10])]
    model = helper.make_model(helper.make_graph([], f"test-{usage}", inputs, outputs))
    metadata = model.metadata_props.add()
    metadata.key = "fixture_marker"
    metadata.value = marker
    onnx.save_model(model, path)
    return path


def _artifact(tmp_path: Path) -> Path:
    path = tmp_path / "expert.onnx"
    _write_test_onnx(path)
    return path


def _vision_entry(path: Path, *, include_receipt: bool = True) -> dict[str, object]:
    entry: dict[str, object] = {
        "path": path.name,
        "state": "approved",
        "installed": True,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "governance": _verified_governance(),
        "inputs": [{"name": "images", "dtype": "float32", "shape": [1, 3, 640, 640]}],
        "outputs": [{"name": "output0", "dtype": "float32", "shape": [1, 58, 8400]}],
        "classes": [f"card-{index}" for index in range(54)],
    }
    if include_receipt:
        entry["promotion_receipt"] = promotion_evidence_fixture(path, entry)
    return entry


def test_file_alone_is_not_available(tmp_path):
    path = _artifact(tmp_path)
    assert not model_artifact_available(path, "expert")
    with pytest.raises(ModelArtifactUnavailable, match="manifest"):
        verify_model_artifact(path, "expert")


def test_legacy_121x5_expert_can_never_be_promoted(tmp_path):
    path = _artifact(tmp_path)
    entry = _expert_entry(
        path,
        state="candidate",
        inputs=[{"name": "obs", "dtype": "float32", "shape": [1, 121]}],
        outputs=[{"name": "logits", "dtype": "float32", "shape": [1, 5]}],
    )
    entry.pop("encoder_revision")
    entry.pop("action_space_revision")
    entry["state"] = "promoted"
    entry["promotion_receipt"] = expert_promotion_evidence_fixture(path, entry)
    manifest = _write_manifest(path, entry)

    with pytest.raises(ModelArtifactUnavailable) as rejection:
        verify_model_artifact(path, "expert", manifest_path=manifest)
    assert rejection.value.code == "expert_contract_legacy"


@pytest.mark.parametrize("schema_version", [None, True, 0, 2, "1"])
def test_schema_version_must_be_exact_integer_one(tmp_path, schema_version):
    path = _artifact(tmp_path)
    manifest = path.parent / "MANIFEST.json"
    manifest.write_text(
        json.dumps({"schema_version": schema_version, "artifacts": [_expert_entry(path)]}),
        encoding="utf-8",
    )
    with pytest.raises(ModelArtifactUnavailable) as raised:
        verify_model_artifact(path, "expert", manifest_path=manifest)
    assert raised.value.code == "schema_version_unsupported"


def test_duplicate_json_keys_are_rejected_at_every_nesting_level(tmp_path):
    path = _artifact(tmp_path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = path.parent / "MANIFEST.json"
    manifest.write_text(
        """{
          "schema_version": 1,
          "artifacts": [{
            "path": "expert.onnx",
            "path": "expert.onnx",
            "state": "approved",
            "installed": true,
            "sha256": "__DIGEST__"
          }]
        }""".replace("__DIGEST__", digest),
        encoding="utf-8",
    )
    with pytest.raises(ModelArtifactUnavailable) as raised:
        verify_model_artifact(path, "expert", manifest_path=manifest)
    assert raised.value.code == "manifest_duplicate_key"


@pytest.mark.parametrize(
    "extra_root",
    [
        {"do-not-echo-root-secret": "do-not-echo-root-value"},
        {"snapshot_date": "2026-02-30"},
    ],
)
def test_manifest_root_is_closed_and_errors_do_not_echo_values(tmp_path, extra_root):
    path = _artifact(tmp_path)
    payload = {"schema_version": 1, "artifacts": [_expert_entry(path)], **extra_root}
    manifest = path.parent / "MANIFEST.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ModelArtifactUnavailable) as raised:
        verify_model_artifact(path, "expert", manifest_path=manifest)

    assert raised.value.code == "manifest_invalid"
    assert "do-not-echo" not in str(raised.value)
    assert raised.value.__cause__ is None


def test_current_repository_manifest_remains_schema_compatible():
    manifest_path = REPOSITORY_ROOT / "backend" / "models" / "MANIFEST.json"
    manifest, _ = model_artifacts._read_manifest(manifest_path)
    assert manifest["snapshot_date"] == "2026-07-17"

    expected_kinds = ["expert", "expert", "vision", "card_reader"]
    for entry, kind in zip(manifest["artifacts"], expected_kinds, strict=True):
        model_artifacts._validate_manifest_entry_schema(entry, kind=kind)


def test_json_integer_digit_bomb_is_rejected_without_parser_details(tmp_path):
    path = _artifact(tmp_path)
    manifest = path.parent / "MANIFEST.json"
    manifest.write_text(
        '{"schema_version":1,"artifacts":[],"do-not-echo":' + "9" * 5000 + "}",
        encoding="utf-8",
    )

    with pytest.raises(ModelArtifactUnavailable) as raised:
        verify_model_artifact(path, "expert", manifest_path=manifest)

    assert raised.value.code == "manifest_invalid"
    assert "do-not-echo" not in str(raised.value)
    assert raised.value.__cause__ is None


def test_deeply_nested_json_is_rejected_without_recursion_escape(tmp_path):
    path = _artifact(tmp_path)
    manifest = path.parent / "MANIFEST.json"
    nested = "[" * 2000 + '"do-not-echo-deep-secret"' + "]" * 2000
    manifest.write_text(
        '{"schema_version":1,"artifacts":' + nested + "}",
        encoding="utf-8",
    )

    with pytest.raises(ModelArtifactUnavailable) as raised:
        verify_model_artifact(path, "expert", manifest_path=manifest)

    assert raised.value.code == "manifest_invalid"
    assert "do-not-echo" not in str(raised.value)
    assert raised.value.__cause__ is None


def test_manifest_cannot_declare_parent_directory_artifact(tmp_path):
    outside = _artifact(tmp_path)
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    entry = _expert_entry(outside, path="../expert.onnx")
    manifest = bundle / "MANIFEST.json"
    manifest.write_text(json.dumps({"schema_version": 1, "artifacts": [entry]}), encoding="utf-8")

    with pytest.raises(ModelArtifactUnavailable) as raised:
        verify_model_artifact(outside, "expert", manifest_path=manifest)

    assert raised.value.code == "artifact_outside_manifest"
    assert raised.value.__cause__ is None


@pytest.mark.parametrize(
    "declared_path",
    [
        "./expert.onnx",
        "nested/../expert.onnx",
        "nested\\expert.onnx",
        "nested//expert.onnx",
        "expert.onnx.",
        "expert.onnx:payload",
        "CON.onnx",
    ],
)
def test_artifact_paths_must_be_portable_canonical_posix_paths(tmp_path, declared_path):
    path = _artifact(tmp_path)
    manifest = _write_manifest(path, _expert_entry(path, path=declared_path))

    with pytest.raises(ModelArtifactUnavailable) as raised:
        verify_model_artifact(path, "expert", manifest_path=manifest)

    assert raised.value.code == "manifest_invalid"


def test_canonical_nested_artifact_path_is_supported(tmp_path):
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    path = model_dir / "expert.onnx"
    _write_test_onnx(path)
    entry = _expert_entry(path, path="models/expert.onnx")
    manifest = tmp_path / "MANIFEST.json"
    manifest.write_text(
        json.dumps({"schema_version": 1, "snapshot_date": "2026-07-18", "artifacts": [entry]}),
        encoding="utf-8",
    )

    receipt = verify_model_artifact(path, "expert", manifest_path=manifest)
    assert receipt.path == path.resolve()


def test_duplicate_artifact_paths_are_rejected_globally(tmp_path):
    path = _artifact(tmp_path)
    entry = _expert_entry(path)
    manifest = path.parent / "MANIFEST.json"
    manifest.write_text(
        json.dumps({"schema_version": 1, "artifacts": [entry, dict(entry)]}),
        encoding="utf-8",
    )

    with pytest.raises(ModelArtifactUnavailable) as raised:
        verify_model_artifact(path, "expert", manifest_path=manifest)

    assert raised.value.code == "artifact_ambiguous"


def test_resolved_artifact_cannot_escape_manifest_directory_without_symlink_privilege(
    tmp_path, monkeypatch
):
    outside = _artifact(tmp_path)
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    link = bundle / "expert.onnx"
    link.write_bytes(outside.read_bytes())
    manifest = bundle / "MANIFEST.json"
    manifest.write_text(
        json.dumps({"schema_version": 1, "artifacts": [_expert_entry(link)]}),
        encoding="utf-8",
    )

    original_resolve = Path.resolve

    def escaped_resolve(path: Path, *args, **kwargs):
        if path == link:
            return outside.resolve()
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", escaped_resolve)

    with pytest.raises(ModelArtifactUnavailable) as raised:
        verify_model_artifact(link, "expert", manifest_path=manifest)

    assert raised.value.code == "artifact_outside_manifest"

    # Exercise a real filesystem link too when the host policy permits it,
    # without turning unavailable Windows developer-mode privilege into a skip.
    monkeypatch.undo()
    link.unlink()
    try:
        link.symlink_to(outside)
    except OSError:
        return
    with pytest.raises(ModelArtifactUnavailable) as real_link_raised:
        verify_model_artifact(link, "expert", manifest_path=manifest)
    assert real_link_raised.value.code == "artifact_outside_manifest"


@pytest.mark.parametrize(
    "updates",
    [
        {"do-not-echo-entry-secret": "do-not-echo-entry-value"},
        {"embedded_metadata": {"unknown": "do-not-echo-metadata-value"}},
        {"producer": "x" * 65},
        {
            "inputs": [
                {
                    "name": "obs",
                    "dtype": "float32",
                    "shape": ["batch", 121],
                    "do-not-echo-tensor-secret": "do-not-echo-tensor-value",
                }
            ]
        },
        {"inference_policy": {"state": "approved", "temperature": 0.0}},
    ],
)
def test_entry_payloads_are_closed_bounded_and_sanitized(tmp_path, updates):
    path = _artifact(tmp_path)
    manifest = _write_manifest(path, _expert_entry(path, **updates))

    with pytest.raises(ModelArtifactUnavailable) as raised:
        verify_model_artifact(path, "expert", manifest_path=manifest)

    assert raised.value.code in {"manifest_invalid", "contract_invalid", "policy_invalid"}
    assert "do-not-echo" not in str(raised.value)


def test_kind_specific_fields_are_closed(tmp_path):
    path = _artifact(tmp_path)
    entry = _expert_entry(
        path,
        inference_policy={
            "state": "approved",
            "temperature": 1.0,
            "min_prob_ratio": 0.0,
            "sizing_jitter": 0.0,
        },
    )
    manifest = _write_manifest(path, entry)

    with pytest.raises(ModelArtifactUnavailable) as raised:
        verify_model_artifact(path, "card_reader", manifest_path=manifest)

    assert raised.value.code == "manifest_invalid"


def test_nonselected_entries_are_also_closed_by_inferred_kind(tmp_path):
    selected = _artifact(tmp_path)
    other = tmp_path / "other.onnx"
    other.write_bytes(b"other-hash-pinned-test-artifact")
    malformed_other = _expert_entry(other, classes=[f"card-{index}" for index in range(52)])
    manifest = tmp_path / "MANIFEST.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "artifacts": [_expert_entry(selected), malformed_other],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ModelArtifactUnavailable) as raised:
        verify_model_artifact(selected, "expert", manifest_path=manifest)

    assert raised.value.code == "manifest_invalid"


def test_missing_lifecycle_has_an_exact_inventory_schema(tmp_path):
    path = _artifact(tmp_path)
    entry = {
        "path": path.name,
        "state": "missing",
        "installed": False,
        "sha256": None,
        "expected_inputs": [{"dtype": "float32", "shape": [1, 121]}],
        "expected_outputs": [{"semantic": "logits", "shape": [1, 5]}],
        "governance": _verified_governance(),
        "inputs": [],
    }
    manifest = _write_manifest(path, entry)

    with pytest.raises(ModelArtifactUnavailable) as raised:
        verify_model_artifact(path, "expert", manifest_path=manifest)

    assert raised.value.code == "manifest_invalid"


@pytest.mark.parametrize(
    ("updates", "code"),
    [
        ({"state": "candidate"}, "state_not_approved"),
        ({"state": "denied"}, "state_invalid"),
        ({"sha256": "0" * 64}, "sha256_mismatch"),
        (
            {
                "governance": {
                    **_verified_governance(),
                    "license": {"status": "denied", "id": None, "reference": None},
                }
            },
            "governance_invalid",
        ),
        (
            {
                "governance": {
                    **_verified_governance(),
                    "lineage": {"status": "fabricated", "id": None, "reference": None},
                }
            },
            "governance_invalid",
        ),
        (
            {
                "governance": {
                    **_verified_governance(),
                    "license": {"status": "unresolved", "id": None, "reference": None},
                }
            },
            "governance_unresolved",
        ),
        (
            {
                "governance": {
                    **_verified_governance(),
                    "lineage": {
                        "status": "verified",
                        "id": "training-run-42",
                        "reference": "not-an-explicit-uri",
                    },
                }
            },
            "governance_invalid",
        ),
        ({"license_status": "resolved_apache_2_0"}, "governance_invalid"),
        ({"inference_policy": {"state": "fabricated"}}, "policy_invalid"),
        (
            {"inputs": [{"name": "obs", "dtype": "float32", "shape": ["batch", 120]}]},
            "contract_mismatch",
        ),
        (
            {"outputs": [{"name": "scores", "dtype": "float32", "shape": ["batch", 5]}]},
            "contract_mismatch",
        ),
    ],
)
def test_each_mandatory_gate_fails_closed(tmp_path, updates, code):
    path = _artifact(tmp_path)
    manifest = _write_manifest(path, _expert_entry(path, **updates))
    with pytest.raises(ModelArtifactUnavailable) as raised:
        verify_model_artifact(path, "expert", manifest_path=manifest)
    assert raised.value.code == code
    assert not model_artifact_available(path, "expert", manifest_path=manifest)


@pytest.mark.parametrize(
    "reference",
    [
        "https://models.example.com/model-card?token=do-not-echo-query-secret",
        "https://models.example.com/model-card#do-not-echo-fragment-secret",
        "https://user:do-not-echo-password@models.example.com/model-card",
        "https://models.example.com:99999/model-card",
        "https://localhost/model-card",
        "https://127.0.0.1/model-card",
        "https://10.0.0.8/model-card",
        "https://169.254.10.20/model-card",
        "https://192.168.1.2/model-card",
        "https://224.0.0.1/model-card",
        "https://0.0.0.0/model-card",
        "https://models.example.com/",
        "urn:poker-arena:test:lineage?token=do-not-echo-urn-secret",
    ],
)
def test_governance_reference_rejects_sensitive_or_nonpublic_urls_without_echo(tmp_path, reference):
    path = _artifact(tmp_path)
    governance = _verified_governance()
    governance["lineage"] = {
        "status": "verified",
        "id": "training-run-42",
        "reference": reference,
    }
    manifest = _write_manifest(path, _expert_entry(path, governance=governance))
    with pytest.raises(ModelArtifactUnavailable) as raised:
        verify_model_artifact(path, "expert", manifest_path=manifest)
    assert raised.value.code == "governance_invalid"
    assert "do-not-echo" not in str(raised.value)


def test_approved_hash_governance_and_contract_return_receipt(tmp_path):
    path = _artifact(tmp_path)
    manifest = _write_manifest(path, _expert_entry(path))
    receipt = verify_model_artifact(path, "expert", manifest_path=manifest)
    assert receipt.path == path.resolve()
    assert receipt.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert receipt.usage == "deployment"
    assert receipt.inference_policy.source == "manifest"
    assert receipt.inference_policy.supported_action_indices == tuple(range(10))
    assert receipt.inference_policy.temperature == 1.0
    assert receipt.inference_policy.min_prob_ratio == 0.0
    assert receipt.inference_policy.sizing_jitter == 0.0


def test_hash_pinned_but_unparseable_onnx_fails_closed(tmp_path):
    path = tmp_path / "expert.onnx"
    path.write_bytes(b"not-an-onnx-protobuf")
    manifest = _write_manifest(path, _expert_entry(path))

    with pytest.raises(ModelArtifactUnavailable) as raised:
        verify_model_artifact(path, "expert", manifest_path=manifest)

    assert raised.value.code == "artifact_uninspectable"


def test_deployable_state_without_scientific_receipt_fails_closed(tmp_path):
    path = tmp_path / "vision.onnx"
    _write_test_onnx(path, usage="vision")
    entry = _vision_entry(path, include_receipt=False)
    manifest = path.parent / "MANIFEST.json"
    manifest.write_text(json.dumps({"schema_version": 1, "artifacts": [entry]}), encoding="utf-8")

    with pytest.raises(ModelArtifactUnavailable) as raised:
        verify_model_artifact(path, "vision", manifest_path=manifest)

    assert raised.value.code == "promotion_evidence_missing"


def test_cached_deployment_revalidates_scientific_receipt(tmp_path):
    path = tmp_path / "vision.onnx"
    _write_test_onnx(path, usage="vision")
    entry = _vision_entry(path)
    manifest = _write_manifest(path, entry)
    verify_model_artifact(path, "vision", manifest_path=manifest)
    evidence = entry["promotion_receipt"]
    assert isinstance(evidence, dict)
    (path.parent / str(evidence["path"])).unlink()

    with pytest.raises(ModelArtifactUnavailable) as raised:
        verify_model_artifact(path, "vision", manifest_path=manifest)

    assert raised.value.code == "promotion_evidence_invalid"


def test_deployment_receipt_rejects_manifest_contract_mutation(tmp_path):
    path = tmp_path / "vision.onnx"
    _write_test_onnx(path, usage="vision")
    entry = _vision_entry(path)
    manifest = _write_manifest(path, entry)
    verify_model_artifact(path, "vision", manifest_path=manifest)

    classes = entry["classes"]
    assert isinstance(classes, list)
    classes[0], classes[1] = classes[1], classes[0]
    governance = entry["governance"]
    assert isinstance(governance, dict)
    lineage = governance["lineage"]
    assert isinstance(lineage, dict)
    lineage["id"] = "different-lineage"
    _write_manifest(path, entry)
    clear_model_artifact_cache()

    with pytest.raises(ModelArtifactUnavailable) as raised:
        verify_model_artifact(path, "vision", manifest_path=manifest)

    assert raised.value.code == "promotion_evidence_invalid"


def test_external_data_onnx_is_rejected_because_sidecar_is_not_hash_bound(tmp_path):
    import numpy as np
    import onnx
    from onnx import TensorProto, helper, numpy_helper

    path = tmp_path / "expert.onnx"
    graph = helper.make_graph(
        [helper.make_node("MatMul", ["obs", "weights"], ["logits"])],
        "external-data-test",
        [helper.make_tensor_value_info("obs", TensorProto.FLOAT, [1, 121])],
        [helper.make_tensor_value_info("logits", TensorProto.FLOAT, [1, 5])],
        [numpy_helper.from_array(np.ones((121, 5), dtype=np.float32), name="weights")],
    )
    model = helper.make_model(graph)
    onnx.save_model(
        model,
        path,
        save_as_external_data=True,
        all_tensors_to_one_file=True,
        location="weights.bin",
        size_threshold=0,
    )
    manifest = _write_manifest(path, _expert_entry(path))

    with pytest.raises(ModelArtifactUnavailable) as raised:
        verify_model_artifact(path, "expert", manifest_path=manifest)

    assert raised.value.code == "external_data_forbidden"


def test_vision_receipt_cannot_authorize_expert_task(tmp_path):
    path = _artifact(tmp_path)
    entry = _expert_entry(path, promotion_receipt=promotion_evidence_fixture(path))
    manifest = _write_manifest(path, entry)

    with pytest.raises(ModelArtifactUnavailable) as raised:
        verify_model_artifact(path, "expert", manifest_path=manifest)

    assert raised.value.code == "promotion_profile_unsupported"


def test_receipt_entry_is_a_defensive_deep_copy(tmp_path):
    path = _artifact(tmp_path)
    manifest = _write_manifest(path, _expert_entry(path))
    receipt = verify_model_artifact(path, "expert", manifest_path=manifest)

    exposed = receipt.entry
    exposed["state"] = "promoted"
    exposed["inputs"][0]["shape"][1] = 999

    assert receipt.entry["state"] == "promoted"
    assert receipt.entry["inputs"][0]["shape"] == ["batch", 208]
    verify_runtime_contract(
        receipt,
        [
            _Node("cards", [1, 208]),
            _Node("global", [1, 24]),
            _Node("seats", [1, 9, 12]),
            _Node("history", [1, 15, 26]),
            _Node("history_mask", [1, 15]),
            _Node("legal_mask", [1, 10]),
        ],
        [_Node("logits", [1, 10])],
    )


def test_v2_expert_rejects_unapproved_action_support_policy(tmp_path):
    path = _artifact(tmp_path)
    entry = _expert_entry(
        path,
        inference_policy={
            "state": "unapproved",
            "temperature": 0.75,
            "min_prob_ratio": 0.15,
            "sizing_jitter": 0.12,
        },
    )
    with pytest.raises(ModelArtifactUnavailable) as rejection:
        verify_model_artifact(path, "expert", manifest_path=_write_manifest(path, entry))
    assert rejection.value.code == "expert_action_support_missing"


def test_approved_manifest_tuning_is_explicitly_loaded(tmp_path):
    path = _artifact(tmp_path)
    entry = _expert_entry(
        path,
        inference_policy={
            "state": "approved",
            "temperature": 0.8,
            "min_prob_ratio": 0.1,
            "sizing_jitter": 0.05,
            "supported_action_indices": [0, 1, 2, 4, 5, 6, 7, 9],
        },
    )
    receipt = verify_model_artifact(path, "expert", manifest_path=_write_manifest(path, entry))
    assert receipt.inference_policy.source == "manifest"
    assert receipt.inference_policy.temperature == 0.8
    assert receipt.inference_policy.min_prob_ratio == 0.1
    assert receipt.inference_policy.sizing_jitter == 0.05
    assert receipt.inference_policy.supported_action_indices == (0, 1, 2, 4, 5, 6, 7, 9)


@pytest.mark.parametrize(
    "supported",
    [None, [], [0, 0], [1, 0], [-1, 0], [0, 10], [False, 1], [0, 1.0]],
)
def test_v2_expert_rejects_invalid_action_support(tmp_path, supported):
    path = _artifact(tmp_path)
    entry = _expert_entry(path)
    policy = dict(entry["inference_policy"])
    if supported is None:
        policy.pop("supported_action_indices")
    else:
        policy["supported_action_indices"] = supported
    entry["inference_policy"] = policy

    with pytest.raises(ModelArtifactUnavailable) as rejection:
        verify_model_artifact(path, "expert", manifest_path=_write_manifest(path, entry))
    assert rejection.value.code == "policy_invalid"


def test_v2_expert_rejects_missing_action_support_policy(tmp_path):
    path = _artifact(tmp_path)
    entry = _expert_entry(path)
    entry.pop("inference_policy")

    with pytest.raises(ModelArtifactUnavailable) as rejection:
        verify_model_artifact(path, "expert", manifest_path=_write_manifest(path, entry))
    assert rejection.value.code == "expert_action_support_missing"


def test_v2_expert_rejects_support_not_proven_by_training_counts(tmp_path):
    path = _artifact(tmp_path)
    entry = _expert_entry(path)
    evidence = dict(entry["training_evidence"])
    trace_path = path.with_name(f"{path.stem}.training_trace.jsonl")
    trace_path.write_text(
        json.dumps({"event": "training_configuration", "source_binding": "a" * 64})
        + "\n"
        + json.dumps(
            {
                "event": "dataset_prepared",
                "optimization_training_class_counts": [
                    100,
                    100,
                    100,
                    0,
                    100,
                    100,
                    100,
                    100,
                    0,
                    100,
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    evidence["trace_sha256"] = hashlib.sha256(trace_path.read_bytes()).hexdigest()
    entry["training_evidence"] = evidence

    with pytest.raises(ModelArtifactUnavailable) as rejection:
        verify_model_artifact(path, "expert", manifest_path=_write_manifest(path, entry))
    assert rejection.value.code == "expert_action_support_mismatch"


def test_candidate_is_evaluable_but_never_deployable(tmp_path):
    path = _artifact(tmp_path)
    manifest = _write_manifest(path, _expert_entry(path, state="candidate"))

    with pytest.raises(ModelArtifactUnavailable) as deployment_rejection:
        verify_model_artifact(path, "expert", manifest_path=manifest)
    assert deployment_rejection.value.code == "state_not_approved"
    assert not model_artifact_available(path, "expert", manifest_path=manifest)

    receipt = verify_evaluation_candidate(path, "expert", manifest_path=manifest)
    assert receipt.usage == "evaluation"
    assert receipt.entry["state"] == "candidate"


def test_deployable_artifact_is_not_silently_accepted_as_candidate(tmp_path):
    path = _artifact(tmp_path)
    manifest = _write_manifest(path, _expert_entry(path, state="approved"))
    with pytest.raises(ModelArtifactUnavailable) as raised:
        verify_evaluation_candidate(path, "expert", manifest_path=manifest)
    assert raised.value.code == "state_not_candidate"


def test_success_receipt_cache_skips_rehash_and_identity_change_revalidates(monkeypatch, tmp_path):
    path = _artifact(tmp_path)
    manifest = _write_manifest(path, _expert_entry(path))
    original_hash = model_artifacts._sha256_file
    calls = 0

    def counted_hash(candidate):
        nonlocal calls
        calls += 1
        return original_hash(candidate)

    monkeypatch.setattr(model_artifacts, "_sha256_file", counted_hash)
    first = verify_model_artifact(path, "expert", manifest_path=manifest)
    second = verify_model_artifact(path, "expert", manifest_path=manifest)
    assert second is first
    # Cache avoids reparsing, but a cache hit still hashes both files. Metadata alone
    # is not a security boundary because size and mtime can be restored by an attacker.
    assert calls == 5

    _write_test_onnx(path, marker="changed")
    _write_manifest(path, _expert_entry(path))
    changed = verify_model_artifact(path, "expert", manifest_path=manifest)
    assert changed.sha256 != first.sha256
    assert calls == 8


def test_success_cache_serializes_concurrent_first_hash(monkeypatch, tmp_path):
    path = _artifact(tmp_path)
    manifest = _write_manifest(path, _expert_entry(path))
    original_hash = model_artifacts._sha256_file
    calls = 0

    def counted_hash(candidate):
        nonlocal calls
        calls += 1
        return original_hash(candidate)

    monkeypatch.setattr(model_artifacts, "_sha256_file", counted_hash)
    with ThreadPoolExecutor(max_workers=8) as pool:
        receipts = list(
            pool.map(
                lambda _: verify_model_artifact(path, "expert", manifest_path=manifest),
                range(16),
            )
        )
    assert calls == 33  # first artifact/evidence hashes + artifact/manifest hash per cache hit
    assert all(receipt is receipts[0] for receipt in receipts)


def test_failed_hash_is_not_cached_and_receipt_detects_post_verify_change(monkeypatch, tmp_path):
    path = _artifact(tmp_path)
    bad_manifest = _write_manifest(path, _expert_entry(path, sha256="0" * 64))
    original_hash = model_artifacts._sha256_file
    calls = 0

    def counted_hash(candidate):
        nonlocal calls
        calls += 1
        return original_hash(candidate)

    monkeypatch.setattr(model_artifacts, "_sha256_file", counted_hash)
    for _ in range(2):
        with pytest.raises(ModelArtifactUnavailable) as raised:
            verify_model_artifact(path, "expert", manifest_path=bad_manifest)
        assert raised.value.code == "sha256_mismatch"
    assert calls == 2

    good_manifest = _write_manifest(path, _expert_entry(path))
    receipt = verify_model_artifact(path, "expert", manifest_path=good_manifest)
    path.write_bytes(path.read_bytes() + b"-race")
    with pytest.raises(ModelArtifactUnavailable) as changed:
        revalidate_model_artifact_identity(receipt)
    assert changed.value.code == "artifact_identity_changed"


def test_same_size_same_mtime_byte_swap_cannot_reuse_cached_receipt(tmp_path):
    path = _artifact(tmp_path)
    manifest = _write_manifest(path, _expert_entry(path))
    receipt = verify_model_artifact(path, "expert", manifest_path=manifest)
    original_stat = path.stat()
    replacement = bytes(byte ^ 0x01 for byte in path.read_bytes())
    assert len(replacement) == original_stat.st_size
    path.write_bytes(replacement)
    os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    assert model_artifacts._file_identity(path, code="artifact_unreadable") == (
        receipt.artifact_identity
    )

    with pytest.raises(ModelArtifactUnavailable) as boundary_rejection:
        revalidate_model_artifact_identity(receipt)
    assert boundary_rejection.value.code == "artifact_content_changed"

    with pytest.raises(ModelArtifactUnavailable) as cache_rejection:
        verify_model_artifact(path, "expert", manifest_path=manifest)
    assert cache_rejection.value.code == "sha256_mismatch"


class _Node:
    def __init__(self, name: str, shape: list[int], dtype: str = "tensor(float)") -> None:
        self.name = name
        self.shape = shape
        self.type = dtype


def test_runtime_graph_must_match_hash_pinned_manifest_contract(tmp_path):
    path = _artifact(tmp_path)
    receipt = verify_model_artifact(
        path, "expert", manifest_path=_write_manifest(path, _expert_entry(path))
    )
    verify_runtime_contract(
        receipt,
        [
            _Node("cards", [1, 208]),
            _Node("global", [1, 24]),
            _Node("seats", [1, 9, 12]),
            _Node("history", [1, 15, 26]),
            _Node("history_mask", [1, 15]),
            _Node("legal_mask", [1, 10]),
        ],
        [_Node("logits", [1, 10])],
    )
    with pytest.raises(ModelArtifactUnavailable) as raised:
        verify_runtime_contract(
            receipt,
            [
                _Node("cards", [1, 103]),
                _Node("global", [1, 24]),
                _Node("seats", [1, 9, 12]),
                _Node("history", [1, 15, 26]),
                _Node("history_mask", [1, 15]),
                _Node("legal_mask", [1, 10]),
            ],
            [_Node("logits", [1, 10])],
        )
    assert raised.value.code == "runtime_contract_mismatch"
