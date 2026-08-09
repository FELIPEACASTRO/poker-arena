"""Fail-closed scientific receipt for a deployable poker Expert.

This module does not decide that a policy is world-class.  It verifies that one
immutable artifact passed a pre-declared local cross-play protocol with bounded
uncertainty, exact runtime invariants and no hidden inference degradation.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

from poker_arena.ml.action_space_v2 import REVISION as ACTION_SPACE_V2_REVISION
from poker_arena.ml.encoder_v2 import REVISION as ENCODER_V2_REVISION
from poker_arena.ml.expert_benchmark import current_execution_binding, summarize_raw_results
from poker_arena.ml.external_validation import ScientificGateError, _load_json

SCHEMA_VERSION: Final = 1
PROFILE_REVISION: Final = "poker-arena-expert-promotion-v1-2026-08-08"
MAX_RECEIPT_BYTES: Final = 4 * 1024 * 1024
MAX_RAW_RESULTS_BYTES: Final = 64 * 1024 * 1024
MAX_TRAINING_RECEIPT_BYTES: Final = 2 * 1024 * 1024
MAX_DATASET_RECEIPT_BYTES: Final = 2 * 1024 * 1024
RECEIPT_MAX_AGE_DAYS: Final = 30
MIN_BLOCKS_PER_CELL: Final = 30
MAX_ONNX_ABS_ERROR: Final = 1e-5
MAX_CI_HALF_WIDTH_BB100: Final = 20.0
MIN_WORST_OPPONENT_LCB_BB100: Final = -5.0

_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}")
_ROOT_FIELDS: Final = frozenset(
    {
        "schema_version",
        "profile_revision",
        "decision",
        "generated_at",
        "artifact_sha256",
        "artifact_contract_sha256",
        "pipeline",
        "protocol",
        "counts",
        "metrics",
        "invariants",
        "raw_results",
        "training_evidence",
    }
)
_PIPELINE_FIELDS: Final = frozenset(
    {
        "git_commit",
        "source_receipt_sha256",
        "dependency_lock_sha256",
        "training_receipt_sha256",
        "raw_results_sha256",
    }
)
_POINTER_FIELDS: Final = frozenset({"path", "sha256"})
_TRAINING_FIELDS: Final = frozenset(
    {
        "schema_version",
        "profile_revision",
        "generated_at",
        "artifact_sha256",
        "artifact_contract_sha256",
        "encoder_revision",
        "action_space_revision",
        "pipeline",
        "dataset",
        "algorithm",
    }
)
_TRAINING_PIPELINE_FIELDS: Final = frozenset(
    {"git_commit", "source_receipt_sha256", "dependency_lock_sha256"}
)
_ALGORITHM_FIELDS: Final = frozenset(
    {"name", "framework", "framework_version", "seeds", "steps", "examples"}
)
_DATASET_FIELDS: Final = frozenset(
    {
        "schema_version",
        "profile_revision",
        "dataset_id",
        "version",
        "license_spdx",
        "source",
        "content_sha256",
        "split_receipt_sha256",
        "permitted_use",
    }
)
TRAINING_PROFILE_REVISION: Final = "poker-arena-expert-training-v1-2026-08-08"
DATASET_PROFILE_REVISION: Final = "poker-arena-expert-dataset-v1-2026-08-08"
_PROTOCOL_FIELDS: Final = frozenset(
    {
        "levels",
        "table_sizes",
        "stack_depths_bb",
        "seat_rotation",
        "duplicate_deals",
        "minimum_blocks_per_cell",
        "alpha",
        "multiplicity",
        "decision_rule",
    }
)
_COUNT_FIELDS: Final = frozenset(
    {"hands", "decisions", "blocks", "illegal_actions", "non_finite_outputs", "fallbacks"}
)
_METRIC_FIELDS: Final = frozenset(
    {
        "onnx_max_abs_error",
        "aggregate_delta_bb100",
        "worst_opponent_delta_bb100",
        "max_ci_half_width_bb100",
        "max_holm_adjusted_p_value",
    }
)
_ESTIMATE_FIELDS: Final = frozenset({"estimate", "simultaneous_ci95"})
_INVARIANT_FIELDS: Final = frozenset(
    {
        "chip_conservation",
        "legal_action",
        "finite_output",
        "same_seed_reproduction",
        "source_onnx_parity",
        "seat_permutation",
        "suit_permutation",
        "hole_order",
        "flop_order",
        "no_private_information_leakage",
        "no_action_aliases",
    }
)


class ExpertPromotionEvidenceError(RuntimeError):
    """Receipt is absent, malformed, stale, inconsistent or below policy."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"expert promotion evidence rejected [{code}]")


@dataclass(frozen=True, slots=True)
class VerifiedExpertPromotionEvidence:
    path: Path
    sha256: str
    artifact_sha256: str
    artifact_contract_sha256: str
    hands: int
    decisions: int


def _exact(value: object, fields: frozenset[str], code: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ExpertPromotionEvidenceError(code)
    return value


def _digest(value: object, code: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ExpertPromotionEvidenceError(code)
    return value


def _finite(value: object, code: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExpertPromotionEvidenceError(code)
    result = float(value)
    if not math.isfinite(result):
        raise ExpertPromotionEvidenceError(code)
    return result


def _count(value: object, code: str) -> int:
    if type(value) is not int or value < 0:
        raise ExpertPromotionEvidenceError(code)
    return value


def _estimate(value: object, code: str) -> tuple[float, float, float]:
    raw = _exact(value, _ESTIMATE_FIELDS, code)
    estimate = _finite(raw["estimate"], code)
    interval = raw["simultaneous_ci95"]
    if not isinstance(interval, list) or len(interval) != 2:
        raise ExpertPromotionEvidenceError(code)
    lower, upper = (_finite(item, code) for item in interval)
    if lower > estimate or estimate > upper:
        raise ExpertPromotionEvidenceError(code)
    return estimate, lower, upper


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _pointer_path(pointer: Mapping[str, Any], base: Path, code: str) -> tuple[Path, str]:
    raw_path = pointer["path"]
    if (
        not isinstance(raw_path, str)
        or re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,126}\.json", raw_path) is None
    ):
        raise ExpertPromotionEvidenceError(code)
    return base / raw_path, _digest(pointer["sha256"], code)


def _load_bound_pointer(
    pointer_value: object,
    *,
    base: Path,
    limit: int,
    code: str,
) -> tuple[Mapping[str, Any], Path, str]:
    pointer = _exact(pointer_value, _POINTER_FIELDS, code)
    path, expected = _pointer_path(pointer, base, code)
    try:
        value, payload = _load_json(path, limit=limit)
    except ScientificGateError as exc:
        raise ExpertPromotionEvidenceError(code) from exc
    if hashlib.sha256(payload).hexdigest() != expected or not isinstance(value, dict):
        raise ExpertPromotionEvidenceError(code)
    return value, path, expected


def _verify_training_evidence(
    pointer: object,
    *,
    receipt_dir: Path,
    artifact_sha256: str,
    artifact_contract_sha256: str,
    pipeline: Mapping[str, Any],
    current_pipeline: Mapping[str, str],
) -> str:
    training, training_path, training_sha = _load_bound_pointer(
        pointer,
        base=receipt_dir,
        limit=MAX_TRAINING_RECEIPT_BYTES,
        code="training_evidence_invalid",
    )
    root = _exact(training, _TRAINING_FIELDS, "training_evidence_invalid")
    if (
        root["schema_version"] != 1
        or root["profile_revision"] != TRAINING_PROFILE_REVISION
        or root["artifact_sha256"] != artifact_sha256
        or root["artifact_contract_sha256"] != artifact_contract_sha256
        or root["encoder_revision"] != ENCODER_V2_REVISION
        or root["action_space_revision"] != ACTION_SPACE_V2_REVISION
    ):
        raise ExpertPromotionEvidenceError("training_evidence_invalid")
    try:
        generated = datetime.strptime(root["generated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=UTC
        )
    except (TypeError, ValueError) as exc:
        raise ExpertPromotionEvidenceError("training_evidence_invalid") from exc
    now = datetime.now(UTC)
    if generated > now + timedelta(minutes=5) or now - generated > timedelta(
        days=RECEIPT_MAX_AGE_DAYS
    ):
        raise ExpertPromotionEvidenceError("training_evidence_invalid")
    training_pipeline = _exact(
        root["pipeline"], _TRAINING_PIPELINE_FIELDS, "training_evidence_invalid"
    )
    if (
        not isinstance(training_pipeline["git_commit"], str)
        or re.fullmatch(r"[0-9a-f]{40}", training_pipeline["git_commit"]) is None
        or any(
            training_pipeline[field] != current_pipeline[field]
            for field in ("source_receipt_sha256", "dependency_lock_sha256")
        )
    ):
        raise ExpertPromotionEvidenceError("training_evidence_invalid")
    algorithm = _exact(root["algorithm"], _ALGORITHM_FIELDS, "training_evidence_invalid")
    if not all(
        isinstance(algorithm[field], str)
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}", algorithm[field])
        for field in ("name", "framework", "framework_version")
    ):
        raise ExpertPromotionEvidenceError("training_evidence_invalid")
    seeds = algorithm["seeds"]
    if (
        not isinstance(seeds, list)
        or len(seeds) < 3
        or any(type(seed) is not int or seed < 0 for seed in seeds)
        or len(set(seeds)) != len(seeds)
        or type(algorithm["steps"]) is not int
        or algorithm["steps"] <= 0
        or type(algorithm["examples"]) is not int
        or algorithm["examples"] <= 0
    ):
        raise ExpertPromotionEvidenceError("training_evidence_invalid")
    dataset, _dataset_path, _dataset_sha = _load_bound_pointer(
        root["dataset"],
        base=training_path.parent,
        limit=MAX_DATASET_RECEIPT_BYTES,
        code="dataset_evidence_invalid",
    )
    dataset_root = _exact(dataset, _DATASET_FIELDS, "dataset_evidence_invalid")
    if (
        dataset_root["schema_version"] != 1
        or dataset_root["profile_revision"] != DATASET_PROFILE_REVISION
        or not all(
            isinstance(dataset_root[field], str) and 1 <= len(dataset_root[field]) <= 128
            for field in ("dataset_id", "version", "license_spdx")
        )
        or not isinstance(dataset_root["source"], str)
        or not (
            dataset_root["source"].startswith("https://")
            or dataset_root["source"].startswith("urn:")
        )
        or dataset_root["permitted_use"] != ["train-expert-v2"]
    ):
        raise ExpertPromotionEvidenceError("dataset_evidence_invalid")
    _digest(dataset_root["content_sha256"], "dataset_evidence_invalid")
    _digest(dataset_root["split_receipt_sha256"], "dataset_evidence_invalid")
    if pipeline["training_receipt_sha256"] != training_sha:
        raise ExpertPromotionEvidenceError("training_evidence_invalid")
    return training_sha


def current_expert_pipeline_binding() -> dict[str, str]:
    """Bind a receipt to the exact backend Python source, lockfile and Git HEAD."""

    backend_root = Path(__file__).resolve().parents[2]
    source_digest = hashlib.sha256()
    for path in sorted(
        (backend_root / "poker_arena").rglob("*.py"), key=lambda item: item.as_posix()
    ):
        relative = path.relative_to(backend_root).as_posix().encode()
        source_digest.update(len(relative).to_bytes(4, "big"))
        source_digest.update(relative)
        source_digest.update(bytes.fromhex(_hash_file(path)))
    git_root = backend_root.parent / ".git"
    head = git_root / "HEAD"
    try:
        head_value = head.read_text(encoding="ascii").strip()
        if head_value.startswith("ref: "):
            ref = head_value[5:]
            if ".." in ref or ref.startswith(("/", "\\")):
                raise ValueError
            commit = (git_root / ref).read_text(encoding="ascii").strip()
        else:
            commit = head_value
    except (OSError, UnicodeError, ValueError) as exc:
        raise ExpertPromotionEvidenceError("pipeline_unverifiable") from exc
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise ExpertPromotionEvidenceError("pipeline_unverifiable")
    return {
        "git_commit": commit,
        "source_receipt_sha256": source_digest.hexdigest(),
        "dependency_lock_sha256": _hash_file(backend_root / "uv.lock"),
    }


def verify_expert_promotion_receipt(
    receipt_path: Path,
    *,
    expected_sha256: str,
    artifact_sha256: str,
    artifact_contract_sha256: str,
    decision_rule: str,
    candidate_manifest_sha256: str | None = None,
) -> VerifiedExpertPromotionEvidence:
    """Verify identity, protocol, uncertainty and invariant gates."""

    _digest(expected_sha256, "receipt_sha256_invalid")
    _digest(artifact_sha256, "artifact_sha256_invalid")
    _digest(artifact_contract_sha256, "contract_sha256_invalid")
    if candidate_manifest_sha256 is not None:
        _digest(candidate_manifest_sha256, "candidate_manifest_sha256_invalid")
    try:
        receipt, payload = _load_json(receipt_path, limit=MAX_RECEIPT_BYTES)
    except ScientificGateError as exc:
        raise ExpertPromotionEvidenceError("receipt_unreadable") from exc
    actual_sha256 = hashlib.sha256(payload).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ExpertPromotionEvidenceError("receipt_sha256_mismatch")

    root = _exact(receipt, _ROOT_FIELDS, "schema_invalid")
    if root["schema_version"] != SCHEMA_VERSION or root["profile_revision"] != PROFILE_REVISION:
        raise ExpertPromotionEvidenceError("profile_unsupported")
    if root["decision"] != "pass":
        raise ExpertPromotionEvidenceError("decision_failed")
    if root["artifact_sha256"] != artifact_sha256:
        raise ExpertPromotionEvidenceError("artifact_mismatch")
    if root["artifact_contract_sha256"] != artifact_contract_sha256:
        raise ExpertPromotionEvidenceError("contract_mismatch")
    try:
        generated = datetime.strptime(root["generated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=UTC
        )
    except (TypeError, ValueError) as exc:
        raise ExpertPromotionEvidenceError("generated_at_invalid") from exc
    now = datetime.now(UTC)
    if generated > now + timedelta(minutes=5) or now - generated > timedelta(
        days=RECEIPT_MAX_AGE_DAYS
    ):
        raise ExpertPromotionEvidenceError("receipt_stale")

    pipeline = _exact(root["pipeline"], _PIPELINE_FIELDS, "pipeline_invalid")
    if (
        not isinstance(pipeline["git_commit"], str)
        or re.fullmatch(r"[0-9a-f]{40}", pipeline["git_commit"]) is None
    ):
        raise ExpertPromotionEvidenceError("pipeline_invalid")
    for field in _PIPELINE_FIELDS - {"git_commit"}:
        _digest(pipeline[field], "pipeline_invalid")
    current_pipeline = current_expert_pipeline_binding()
    for field in ("source_receipt_sha256", "dependency_lock_sha256"):
        if pipeline[field] != current_pipeline[field]:
            raise ExpertPromotionEvidenceError("pipeline_mismatch")

    _verify_training_evidence(
        root["training_evidence"],
        receipt_dir=receipt_path.parent,
        artifact_sha256=artifact_sha256,
        artifact_contract_sha256=artifact_contract_sha256,
        pipeline=pipeline,
        current_pipeline=current_pipeline,
    )

    protocol = _exact(root["protocol"], _PROTOCOL_FIELDS, "protocol_invalid")
    if protocol != {
        "levels": ["beginner", "intermediate", "advanced"],
        "table_sizes": [2, 6, 9],
        "stack_depths_bb": [20, 50, 100, 200],
        "seat_rotation": "all-seats",
        "duplicate_deals": True,
        "minimum_blocks_per_cell": MIN_BLOCKS_PER_CELL,
        "alpha": 0.05,
        "multiplicity": "holm",
        "decision_rule": decision_rule,
    } or decision_rule not in {"modal", "sampled"}:
        raise ExpertPromotionEvidenceError("protocol_invalid")

    pointer = _exact(root["raw_results"], _POINTER_FIELDS, "raw_results_invalid")
    raw_path = pointer["path"]
    if (
        not isinstance(raw_path, str)
        or re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,126}\.json", raw_path) is None
    ):
        raise ExpertPromotionEvidenceError("raw_results_invalid")
    raw_digest = _digest(pointer["sha256"], "raw_results_invalid")
    if pipeline["raw_results_sha256"] != raw_digest:
        raise ExpertPromotionEvidenceError("raw_results_invalid")
    try:
        raw_results, raw_payload = _load_json(
            receipt_path.parent / raw_path, limit=MAX_RAW_RESULTS_BYTES
        )
        if hashlib.sha256(raw_payload).hexdigest() != raw_digest:
            raise ExpertPromotionEvidenceError("raw_results_mismatch")
        raw_summary = summarize_raw_results(raw_results)
    except ScientificGateError as exc:
        raise ExpertPromotionEvidenceError("raw_results_unreadable") from exc
    except ValueError as exc:
        raise ExpertPromotionEvidenceError("raw_results_invalid") from exc
    if not isinstance(raw_results, dict) or not isinstance(raw_results.get("execution"), dict):
        raise ExpertPromotionEvidenceError("raw_results_invalid")
    execution = raw_results["execution"]
    if (
        execution.get("candidate_artifact_sha256") != artifact_sha256
        or (
            candidate_manifest_sha256 is not None
            and execution.get("candidate_manifest_sha256") != candidate_manifest_sha256
        )
        or execution.get("candidate_contract_sha256") != artifact_contract_sha256
        or execution.get("decision_rule") != decision_rule
        or any(
            execution.get(field) != value for field, value in current_execution_binding().items()
        )
    ):
        raise ExpertPromotionEvidenceError("raw_execution_mismatch")

    counts = _exact(root["counts"], _COUNT_FIELDS, "counts_invalid")
    parsed_counts = {field: _count(counts[field], "counts_invalid") for field in _COUNT_FIELDS}
    minimum_cells = 3 * 3 * 4
    if (
        parsed_counts["hands"] != raw_summary.hands
        or parsed_counts["decisions"] != raw_summary.decisions
        or parsed_counts["blocks"] != raw_summary.blocks
        or parsed_counts["blocks"] < minimum_cells * MIN_BLOCKS_PER_CELL
        or any(
            parsed_counts[field] != 0
            for field in ("illegal_actions", "non_finite_outputs", "fallbacks")
        )
        or parsed_counts["illegal_actions"] != raw_summary.illegal_actions
        or parsed_counts["non_finite_outputs"] != raw_summary.non_finite_outputs
        or parsed_counts["fallbacks"] != raw_summary.fallbacks
    ):
        raise ExpertPromotionEvidenceError("counts_below_policy")

    metrics = _exact(root["metrics"], _METRIC_FIELDS, "metrics_invalid")
    parity = _finite(metrics["onnx_max_abs_error"], "metrics_invalid")
    aggregate = _estimate(metrics["aggregate_delta_bb100"], "metrics_invalid")
    worst = _estimate(metrics["worst_opponent_delta_bb100"], "metrics_invalid")
    ci_half_width = _finite(metrics["max_ci_half_width_bb100"], "metrics_invalid")
    max_holm_p = _finite(metrics["max_holm_adjusted_p_value"], "metrics_invalid")
    if (
        any(
            not math.isclose(observed, expected, rel_tol=1e-9, abs_tol=1e-9)
            for observed, expected in zip(aggregate, raw_summary.aggregate, strict=True)
        )
        or any(
            not math.isclose(observed, expected, rel_tol=1e-9, abs_tol=1e-9)
            for observed, expected in zip(worst, raw_summary.worst_cell, strict=True)
        )
        or not math.isclose(
            ci_half_width, raw_summary.max_ci_half_width, rel_tol=1e-9, abs_tol=1e-9
        )
        or not math.isclose(
            max_holm_p,
            raw_summary.max_holm_adjusted_p_value,
            rel_tol=1e-9,
            abs_tol=1e-9,
        )
    ):
        raise ExpertPromotionEvidenceError("metrics_not_derived")
    _, aggregate_lower, _ = aggregate
    _, worst_lower, _ = worst
    if (
        parity < 0.0
        or parity > MAX_ONNX_ABS_ERROR
        or aggregate_lower <= 0.0
        or worst_lower < MIN_WORST_OPPONENT_LCB_BB100
        or ci_half_width < 0.0
        or ci_half_width > MAX_CI_HALF_WIDTH_BB100
        or max_holm_p < 0.0
        or max_holm_p > 0.05
    ):
        raise ExpertPromotionEvidenceError("metrics_below_policy")

    invariants = _exact(root["invariants"], _INVARIANT_FIELDS, "invariants_invalid")
    if any(invariants[field] is not True for field in _INVARIANT_FIELDS):
        raise ExpertPromotionEvidenceError("invariants_failed")

    return VerifiedExpertPromotionEvidence(
        path=receipt_path.resolve(),
        sha256=actual_sha256,
        artifact_sha256=artifact_sha256,
        artifact_contract_sha256=artifact_contract_sha256,
        hands=parsed_counts["hands"],
        decisions=parsed_counts["decisions"],
    )
