from __future__ import annotations

import gc
import hashlib
import hmac
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from poker_arena.ml import data_manifest, external_validation
from poker_arena.ml.external_validation import (
    PromotionEvidenceError,
    ScientificGateError,
    evaluate_external_holdout,
    verify_promotion_receipt,
    write_receipt,
)
from tests.helpers.model_manifest import promotion_evidence_fixture

_REAL_CANDIDATE_RUNNER = external_validation._candidate_runner


@pytest.fixture(autouse=True)
def _trusted_runtime_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    def factory(_artifact: Path, _manifest: Path):
        return lambda _image: (
            {
                "hole": ["As", "Kd"],
                "board": ["2h", "6c", "Tc"],
                "pot": 700,
                "n_players": None,
                "position": None,
            },
            0.99,
            True,
            10.0,
        )

    monkeypatch.setattr(external_validation, "_candidate_runner", factory)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _player(value: str) -> str:
    return hmac.new(b"test-only-key", value.encode(), hashlib.sha256).hexdigest()


def _sample(path: Path, sample_id: str, split: str, *, group: str) -> dict[str, object]:
    external = split == external_validation.EXTERNAL_SPLIT
    return {
        "id": sample_id,
        "path": path.name,
        "sha256": _sha(path),
        "source": f"source-{group}",
        "source_version": "2026.07.18",
        "session": f"session-{group}",
        "client": f"client-{group}",
        "theme": f"theme-{group}",
        "deck": f"deck-{group}",
        "hashed_player_id": _player(f"player-{group}"),
        "event_time": "2026-03-01T00:00:00Z" if external else "2026-01-01T00:00:00Z",
        "split_group": f"group-{group}",
        "split": split,
        "license": "CC-BY-4.0",
    }


def _manifest(samples: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "profile_revision": data_manifest.PROFILE_REVISION,
        "dataset": {"name": "external-fixture", "version": "1.0.0"},
        "policy": {
            "allowed_splits": ["train", external_validation.EXTERNAL_SPLIT],
            "allowed_licenses": ["CC-BY-4.0"],
            "group_disjoint_keys": [["source", "session"], ["client", "theme", "deck"]],
            "reject_duplicates_within_split": True,
            "consent": {"status": "obtained", "evidence_reference": "consent-fixture-v1"},
            "legal_basis": {"basis": "consent", "evidence_reference": "legal-fixture-v1"},
            "redaction": {
                "direct_identifiers_removed": True,
                "screen_names_removed": True,
                "free_text_reviewed": True,
                "verification": "automated-and-human",
            },
            "permitted_use": ["model-evaluation"],
            "real_money": False,
            "platform_terms": {
                "status": "reviewed-compatible",
                "evidence_reference": "terms-fixture-v1",
            },
            "jurisdiction": ["BR"],
            "player_identity": {
                "scheme": "hmac-sha256",
                "key_version": "kv-player-fixture-v1",
                "separation_context": "poker-arena/player-fixture/v1",
                "purpose": "split-leakage-prevention",
            },
            "retention": {"expires_at": "2099-12-31T23:59:59Z", "review_interval_days": 365},
            "deletion": {
                "on_request": True,
                "on_retention_expiry": True,
                "procedure_id": "delete-fixture-v1",
                "verification_required": True,
            },
            "temporal_order": {
                "split_order": ["train", external_validation.EXTERNAL_SPLIT],
                "allow_equal_boundary": False,
            },
        },
        "samples": samples,
    }


def _fixture(
    tmp_path: Path, *, near_duplicate: bool = False
) -> tuple[Path, Path, Path, Path, Path]:
    artifact = tmp_path / "vision.onnx"
    artifact.write_bytes(b"candidate-vision-model")
    candidate_manifest = tmp_path / "candidate-manifest.json"
    candidate_manifest.write_text("{}", encoding="utf-8")
    train = tmp_path / "train.png"
    Image.new("RGB", (10, 10), "black").save(train)
    external = tmp_path / "external.png"
    image = Image.new("RGB", (11, 11), "black" if near_duplicate else "white")
    if not near_duplicate:
        for index in range(11):
            image.putpixel((index, index), (0, 0, 0))
    else:
        image.putpixel((0, 0), (1, 1, 1))
    image.save(external)
    truth = tmp_path / "truth.json"
    truth.write_text(
        json.dumps({"hole": ["As", "Kd"], "board": ["2h", "6c", "Tc"], "pot": 700}),
        encoding="utf-8",
    )
    protocol = tmp_path / "annotation-protocol.json"
    protocol.write_text('{"protocol":"double-blind-v1"}', encoding="utf-8")
    samples = [
        _sample(train, "train-image", "train", group="train"),
        _sample(protocol, "annotation-protocol", "train", group="protocol"),
        _sample(external, "external-image", external_validation.EXTERNAL_SPLIT, group="external"),
        _sample(truth, "external-truth", external_validation.EXTERNAL_SPLIT, group="external"),
    ]
    manifest = tmp_path / "dataset-manifest.json"
    manifest.write_text(json.dumps(_manifest(samples)), encoding="utf-8")
    observations = tmp_path / "observations.json"
    observations.write_text(
        json.dumps(
            {
                "schema_version": external_validation.SCHEMA_VERSION,
                "profile_revision": external_validation.PROFILE_REVISION,
                "artifact_sha256": _sha(artifact),
                "pipeline": external_validation.current_pipeline_binding(),
                "annotation_protocol": {
                    "id": "double-blind-v1",
                    "version": "v1",
                    "preregistered_at": "2025-12-01T00:00:00Z",
                    "evidence_sample_id": "annotation-protocol",
                    "evidence_sha256": _sha(protocol),
                    "min_annotators": 2,
                    "adjudication": "required-for-disagreement",
                    "blind_to_model": True,
                },
                "records": [
                    {
                        "id": "observation-1",
                        "image_sample_id": "external-image",
                        "truth_sample_id": "external-truth",
                        "annotation": {
                            "annotator_count": 2,
                            "agreement": True,
                            "adjudicated": False,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return artifact, candidate_manifest, manifest, observations, protocol


def test_one_real_screen_can_never_authorize_promotion(tmp_path: Path) -> None:
    artifact, candidate_manifest, manifest, observations, _protocol = _fixture(tmp_path)

    receipt = evaluate_external_holdout(
        artifact, candidate_manifest, manifest, tmp_path, observations
    )

    assert receipt["decision"] == "fail"
    codes = {failure["code"] for failure in receipt["failures"]}
    assert {
        "insufficient_holdout",
        "insufficient_diversity",
        "insufficient_accepted_predictions",
        "subgroup_too_small",
    }.issubset(codes)
    assert receipt["counts"]["total"] == 1
    assert receipt["execution_environment"]["execution_provider"] == "CPUExecutionProvider"
    assert receipt["execution_environment"]["warmup_discarded"] is False


def test_near_duplicate_across_development_and_external_splits_blocks(tmp_path: Path) -> None:
    artifact, candidate_manifest, manifest, observations, _protocol = _fixture(
        tmp_path, near_duplicate=True
    )

    receipt = evaluate_external_holdout(
        artifact, candidate_manifest, manifest, tmp_path, observations
    )

    assert "near_duplicate_leakage" in {
        failure["code"] for failure in receipt["failures"]
    }


def test_annotation_without_two_annotators_fails_before_metrics(tmp_path: Path) -> None:
    artifact, candidate_manifest, manifest, observations, _protocol = _fixture(tmp_path)
    payload = json.loads(observations.read_text(encoding="utf-8"))
    payload["records"][0]["annotation"]["annotator_count"] = 1
    observations.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ScientificGateError, match="annotation"):
        evaluate_external_holdout(
            artifact, candidate_manifest, manifest, tmp_path, observations
        )


def test_failed_scientific_receipt_is_never_valid_promotion_evidence(tmp_path: Path) -> None:
    artifact, candidate_manifest, manifest, observations, _protocol = _fixture(tmp_path)
    receipt = evaluate_external_holdout(
        artifact, candidate_manifest, manifest, tmp_path, observations
    )
    receipt_path = tmp_path / "failed-receipt.json"
    digest = write_receipt(receipt_path, receipt)

    with pytest.raises(PromotionEvidenceError) as raised:
        verify_promotion_receipt(
            receipt_path,
            expected_sha256=digest,
            artifact_sha256=_sha(artifact),
        )

    assert raised.value.code == "receipt_failed"


def test_hash_pinned_pass_receipt_verifier_detects_tampering(tmp_path: Path) -> None:
    artifact = tmp_path / "model.onnx"
    artifact.write_bytes(b"test-model")
    evidence = promotion_evidence_fixture(artifact)
    receipt = tmp_path / evidence["path"]
    verified = verify_promotion_receipt(
        receipt,
        expected_sha256=evidence["sha256"],
        artifact_sha256=_sha(artifact),
    )
    assert verified.sha256 == evidence["sha256"]

    receipt.write_bytes(receipt.read_bytes() + b" ")
    with pytest.raises(PromotionEvidenceError) as raised:
        verify_promotion_receipt(
            receipt,
            expected_sha256=evidence["sha256"],
            artifact_sha256=_sha(artifact),
        )
    assert raised.value.code == "receipt_sha256_mismatch"


def test_pass_receipt_requires_complete_execution_environment(tmp_path: Path) -> None:
    artifact = tmp_path / "model.onnx"
    artifact.write_bytes(b"test-model")
    evidence = promotion_evidence_fixture(artifact)
    receipt_path = tmp_path / evidence["path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    del receipt["execution_environment"]["onnxruntime"]
    replacement = tmp_path / "incomplete-environment.json"
    digest = write_receipt(replacement, receipt)

    with pytest.raises(PromotionEvidenceError) as raised:
        verify_promotion_receipt(
            replacement,
            expected_sha256=digest,
            artifact_sha256=_sha(artifact),
        )

    assert raised.value.code == "receipt_invalid"


def test_pass_receipt_is_invalidated_by_runtime_pipeline_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = tmp_path / "model.onnx"
    artifact.write_bytes(b"test-model")
    evidence = promotion_evidence_fixture(artifact)
    receipt = tmp_path / evidence["path"]
    changed = external_validation.current_pipeline_binding()
    changed["source_receipt_sha256"] = "0" * 64
    monkeypatch.setattr(external_validation, "current_pipeline_binding", lambda: changed)

    with pytest.raises(PromotionEvidenceError) as raised:
        verify_promotion_receipt(
            receipt,
            expected_sha256=evidence["sha256"],
            artifact_sha256=_sha(artifact),
        )

    assert raised.value.code == "pipeline_mismatch"


def test_banded_near_duplicate_search_is_bounded_fail_closed() -> None:
    signatures = [(index << 13, "train" if index % 2 else "external-test") for index in range(5000)]
    assert external_validation._near_duplicate_status(signatures) in {
        "leakage",
        "ambiguous",
    }


def test_oversized_image_is_rejected_before_pixel_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class OversizedImage:
        width = external_validation.MAX_IMAGE_DIMENSION + 1
        height = 2

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def load(self):
            pytest.fail("oversized image must be rejected before allocation")

    monkeypatch.setattr(external_validation.Image, "open", lambda _path: OversizedImage())

    with pytest.raises(ScientificGateError, match="dimensions"):
        external_validation._image_signature(b"synthetic-image-header")


def test_stale_pipeline_binding_is_rejected_before_evaluation(tmp_path: Path) -> None:
    artifact, candidate_manifest, manifest, observations, _protocol = _fixture(tmp_path)
    payload = json.loads(observations.read_text(encoding="utf-8"))
    payload["pipeline"]["inference_config_sha256"] = "0" * 64
    observations.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ScientificGateError, match="stale"):
        evaluate_external_holdout(
            artifact, candidate_manifest, manifest, tmp_path, observations
        )


@pytest.mark.parametrize(
    ("relative_path", "replacement"),
    [
        ("external.png", b"changed-image-after-manifest-validation"),
        ("truth.json", b'{"hole":["Ah","Kh"],"board":[],"pot":1}'),
        ("annotation-protocol.json", b'{"protocol":"changed-after-validation"}'),
    ],
)
def test_sample_change_after_manifest_validation_is_detected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative_path: str,
    replacement: bytes,
) -> None:
    artifact, candidate_manifest, manifest, observations, _protocol = _fixture(tmp_path)
    original_validate = external_validation.validate_manifest

    def validate_then_change(*args, **kwargs):
        report = original_validate(*args, **kwargs)
        (tmp_path / relative_path).write_bytes(replacement)
        return report

    monkeypatch.setattr(external_validation, "validate_manifest", validate_then_change)

    with pytest.raises(ScientificGateError, match="digest differs"):
        evaluate_external_holdout(
            artifact, candidate_manifest, manifest, tmp_path, observations
        )


def test_gate_retains_only_constant_number_of_sample_payloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, candidate_manifest, manifest, observations, _protocol = _fixture(tmp_path)
    original_snapshot = external_validation._sample_snapshot
    counters = {"active": 0, "maximum": 0}

    class TrackedPayload(bytes):
        def __new__(cls, payload: bytes):
            instance = super().__new__(cls, payload)
            counters["active"] += 1
            counters["maximum"] = max(counters["maximum"], counters["active"])
            return instance

        def __del__(self):
            counters["active"] -= 1

    def tracked_snapshot(*args, **kwargs):
        return TrackedPayload(original_snapshot(*args, **kwargs))

    monkeypatch.setattr(external_validation, "_sample_snapshot", tracked_snapshot)

    receipt = evaluate_external_holdout(
        artifact, candidate_manifest, manifest, tmp_path, observations
    )
    gc.collect()

    assert receipt["counts"]["total"] == 1
    assert counters["active"] == 0
    assert counters["maximum"] <= 2


def test_trusted_runner_latency_covers_decode_inference_and_sanity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import poker_arena.model_artifacts as artifacts_module
    import poker_arena.vision.onnx_recognize as onnx_module
    import poker_arena.vision.sanity as sanity_module

    events: list[str] = []
    clock_values = iter((10.0, 10.5))

    def clock() -> float:
        events.append("clock")
        return next(clock_values)

    original_open = external_validation.Image.open

    def checked_open(payload):
        assert events == ["clock"]
        events.append("decode")
        return original_open(payload)

    class Recognizer:
        def __init__(self, *_args, **_kwargs):
            pass

        def recognize(self, *_args):
            events.append("inference")
            return SimpleNamespace(
                hole=["As", "Kd"],
                board=[],
                pot=10,
                n_players=2,
                position="BTN",
                confidence=0.99,
                card_confidences=[0.99, 0.99],
                pot_confidence=0.99,
            )

    def sanity(_state, **_kwargs):
        events.append("sanity")
        return SimpleNamespace(ok=True)

    artifact = SimpleNamespace(
        path=tmp_path / "candidate.onnx",
        manifest_path=tmp_path / "MANIFEST.candidate.json",
    )
    monkeypatch.setattr(external_validation.Image, "open", checked_open)
    monkeypatch.setattr(artifacts_module, "verify_evaluation_candidate", lambda *_a, **_k: artifact)
    monkeypatch.setattr(onnx_module, "OnnxRecognizer", Recognizer)
    monkeypatch.setattr(sanity_module, "check_state", sanity)
    image = tmp_path / "tiny.png"
    Image.new("RGB", (4, 4), "white").save(image)

    runner = _REAL_CANDIDATE_RUNNER(
        artifact.path, artifact.manifest_path, _clock=clock
    )
    _prediction, _confidence, accepted, latency_ms = runner(image.read_bytes())

    assert accepted is True
    assert latency_ms == 500.0
    assert events == ["clock", "decode", "inference", "sanity", "clock"]
