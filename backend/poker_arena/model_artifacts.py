"""Fail-closed governance gate for local model artifacts.

An ONNX file is not deployable merely because it exists.  Every loader routes through
this module and requires an adjacent (or explicitly configured) ``MANIFEST.json`` entry
whose state, digest, governance fields and declared tensor contract are acceptable.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import os
import re
import stat as stat_module
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Final, Literal
from urllib.parse import urlsplit

from poker_arena.ml.action_space_v2 import REVISION as EXPERT_ACTION_SPACE_V2
from poker_arena.ml.encoder_v2 import REVISION as EXPERT_ENCODER_V2
from poker_arena.ml.expert_validation import (
    PROFILE_REVISION as EXPERT_PROMOTION_PROFILE_REVISION,
)
from poker_arena.ml.expert_validation import (
    ExpertPromotionEvidenceError,
    verify_expert_promotion_receipt,
)
from poker_arena.ml.external_validation import (
    PROFILE_REVISION as PROMOTION_PROFILE_REVISION,
)
from poker_arena.ml.external_validation import (
    PromotionEvidenceError,
    verify_promotion_receipt,
)
from poker_arena.ml.promotion_contract import promotion_contract_sha256

ArtifactKind = Literal["expert", "vision", "card_reader"]
ArtifactUsage = Literal["deployment", "evaluation"]
ShapeDim = int | str

_SCHEMA_VERSION: Final = 1
_APPROVED_STATES: Final = frozenset({"approved", "promoted"})
_ARTIFACT_STATES: Final = frozenset({"approved", "promoted", "candidate", "quarantined", "missing"})
_GOVERNANCE_STATUSES: Final = frozenset({"verified", "unresolved"})
_POLICY_STATES: Final = frozenset({"approved", "promoted", "unapproved"})
_MAX_MANIFEST_BYTES: Final = 2 * 1024 * 1024
_MAX_TRAINING_EVIDENCE_BYTES: Final = 8 * 1024 * 1024
_MAX_ARTIFACT_BYTES: Final = 16 * 1024 * 1024 * 1024
_MAX_ONNX_PROTO_INSPECTION_BYTES: Final = 512 * 1024 * 1024
_MAX_ARTIFACTS: Final = 256
_MAX_ARTIFACT_PATH_CHARS: Final = 512
_MAX_TEXT_CHARS: Final = 1024
_MAX_SYMBOLIC_DIM_CHARS: Final = 64
_MAX_SHAPE_RANK: Final = 8
_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}")
_CANONICAL_PATH_PART_RE: Final = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,126}[A-Za-z0-9_-])?")
_SAFE_IDENTIFIER_RE: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}")
_SYMBOLIC_DIM_RE: Final = re.compile(r"\*?[A-Za-z][A-Za-z0-9_-]{0,63}")
_GOVERNANCE_ID_RE: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+/-]{0,127}")
_PUBLIC_HOST_LABEL_RE: Final = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_URN_RE: Final = re.compile(
    r"urn:[a-z0-9][a-z0-9-]{1,31}:[A-Za-z0-9][A-Za-z0-9._~:/@!$&'()*+,;=%-]{0,1023}"
)
_UNRESOLVED_PREFIXES: Final = (
    "missing",
    "partial",
    "pending",
    "unknown",
    "unresolved",
    "unverified",
)
_ROOT_REQUIRED_FIELDS: Final = frozenset({"schema_version", "artifacts"})
_ROOT_ALLOWED_FIELDS: Final = _ROOT_REQUIRED_FIELDS | {"snapshot_date"}
_BASE_ENTRY_FIELDS: Final = frozenset(
    {"path", "state", "installed", "sha256", "governance", "inputs", "outputs"}
)
_COMMON_OPTIONAL_ENTRY_FIELDS: Final = frozenset(
    {"size_bytes", "producer", "embedded_metadata", "promotion_receipt"}
)
_KIND_OPTIONAL_ENTRY_FIELDS: Final[dict[ArtifactKind, frozenset[str]]] = {
    "expert": frozenset(
        {
            "inference_policy",
            "training_context",
            "encoder_revision",
            "action_space_revision",
            "training_evidence",
        }
    ),
    "vision": frozenset({"classes"}),
    "card_reader": frozenset(),
}
_NONMISSING_ENTRY_FIELDS: Final = (
    _BASE_ENTRY_FIELDS
    | _COMMON_OPTIONAL_ENTRY_FIELDS
    | frozenset().union(*_KIND_OPTIONAL_ENTRY_FIELDS.values())
)
_MISSING_ENTRY_FIELDS: Final = frozenset(
    {
        "path",
        "state",
        "installed",
        "sha256",
        "expected_inputs",
        "expected_outputs",
        "governance",
    }
)
_EMBEDDED_METADATA_FIELDS: Final = frozenset(
    {
        "architecture",
        "ultralytics_version",
        "task",
        "training_data_path",
        "export_date",
        "license",
    }
)
_TRAINING_CONTEXT_FIELDS: Final = frozenset(
    {
        "project_commit",
        "dataset_commit",
        "dataset_tree",
        "dataset_split_receipt_sha256",
        "phh_corpus_governance_receipt_sha256",
    }
)
_INFERENCE_POLICY_FIELDS: Final = frozenset(
    {
        "state",
        "decision_rule",
        "temperature",
        "min_prob_ratio",
        "sizing_jitter",
        "supported_action_indices",
    }
)
_TRAINING_EVIDENCE_FIELDS: Final = frozenset(
    {"metrics_path", "metrics_sha256", "trace_path", "trace_sha256"}
)
_DECISION_RULES: Final = frozenset({"modal", "sampled"})
_PROMOTION_RECEIPT_FIELDS: Final = frozenset(
    {"path", "sha256", "profile_revision", "artifact_contract_sha256"}
)
_WINDOWS_RESERVED_PATH_STEMS: Final = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
    }
)


class ModelArtifactUnavailable(RuntimeError):
    """Artifact failed a mandatory governance, identity or contract check."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"model artifact rejected [{code}]: {detail}")


@dataclass(frozen=True)
class InferencePolicy:
    """Post-processing applied to Expert probabilities and raise sizing."""

    decision_rule: Literal["modal", "sampled"] = "sampled"
    temperature: float = 1.0
    min_prob_ratio: float = 0.0
    sizing_jitter: float = 0.0
    supported_action_indices: tuple[int, ...] = ()
    source: Literal["neutral", "manifest"] = "neutral"


@dataclass(frozen=True)
class VerifiedModelArtifact:
    """Immutable receipt returned only after every static gate passes."""

    path: Path
    manifest_path: Path
    sha256: str
    manifest_sha256: str
    kind: ArtifactKind
    usage: ArtifactUsage
    _entry: Mapping[str, Any] = field(compare=False, hash=False, repr=False)
    inference_policy: InferencePolicy
    artifact_identity: FileIdentity
    manifest_identity: FileIdentity

    @property
    def entry(self) -> dict[str, Any]:
        """Return a defensive JSON-shaped copy of the verified manifest entry."""

        thawed = _thaw_json(self._entry)
        if not isinstance(thawed, dict):
            raise RuntimeError("verified artifact entry lost its object shape")
        return thawed


@dataclass(frozen=True)
class FileIdentity:
    """Filesystem identity used to invalidate successful verification receipts."""

    device: int
    inode: int
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class _CachedReceipt:
    receipt: VerifiedModelArtifact
    artifact_identity: FileIdentity
    manifest_identity: FileIdentity


_RECEIPT_CACHE: Final[dict[tuple[ArtifactUsage, ArtifactKind, str, str], _CachedReceipt]] = {}
_RECEIPT_CACHE_LOCK: Final = threading.RLock()


@dataclass(frozen=True)
class _TensorRule:
    name: str | None
    dtype: str
    shapes: tuple[tuple[ShapeDim, ...], ...]


@dataclass(frozen=True)
class _ContractRule:
    inputs: tuple[_TensorRule, ...]
    outputs: tuple[_TensorRule, ...]
    class_counts: frozenset[int] = frozenset()


_EXPERT_V1_CONTRACT: Final = _ContractRule(
    inputs=(_TensorRule("obs", "float32", (("*batch", 121),)),),
    outputs=(_TensorRule("logits", "float32", (("*batch", 5),)),),
)
_EXPERT_V2_CONTRACT: Final = _ContractRule(
    inputs=(
        _TensorRule("cards", "float32", (("*batch", 208),)),
        _TensorRule("global", "float32", (("*batch", 24),)),
        _TensorRule("seats", "float32", (("*batch", 9, 12),)),
        _TensorRule("history", "float32", (("*batch", 15, 26),)),
        _TensorRule("history_mask", "float32", (("*batch", 15),)),
        _TensorRule("legal_mask", "float32", (("*batch", 10),)),
    ),
    outputs=(_TensorRule("logits", "float32", (("*batch", 10),)),),
)

_CONTRACTS: Final[dict[ArtifactKind, _ContractRule]] = {
    "expert": _EXPERT_V1_CONTRACT,
    "vision": _ContractRule(
        inputs=(_TensorRule("images", "float32", (("*batch", 3, 640, 640),)),),
        outputs=(
            _TensorRule(
                "output0",
                "float32",
                (
                    ("*batch", 56, "*anchors"),
                    ("*batch", 58, "*anchors"),
                    ("*batch", "*anchors", 56),
                    ("*batch", "*anchors", 58),
                ),
            ),
        ),
        class_counts=frozenset({52, 54}),
    ),
    "card_reader": _ContractRule(
        inputs=(_TensorRule(None, "float32", (("*batch", 3, 96, 64),)),),
        outputs=(
            _TensorRule(None, "float32", (("*batch", 13),)),
            _TensorRule(None, "float32", (("*batch", 4),)),
        ),
    ),
}


def model_manifest_path(model_path: str | Path, specific_env: str | None = None) -> Path:
    """Resolve the manifest without granting a bypass for custom model paths."""

    if specific_env:
        configured = os.environ.get(specific_env)
        if configured:
            return Path(configured)
    shared = os.environ.get("POKER_MODEL_MANIFEST")
    if shared:
        return Path(shared)
    return Path(model_path).parent / "MANIFEST.json"


def _file_identity(path: Path, *, code: str) -> FileIdentity:
    try:
        stat = path.stat()
    except OSError:
        raise ModelArtifactUnavailable(code, "file metadata could not be read") from None
    if not stat_module.S_ISREG(stat.st_mode):
        raise ModelArtifactUnavailable(code, "path is not a regular file")
    return FileIdentity(
        device=stat.st_dev,
        inode=stat.st_ino,
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
    )


def clear_model_artifact_cache() -> None:
    """Drop successful receipts; failures are never cached."""

    with _RECEIPT_CACHE_LOCK:
        _RECEIPT_CACHE.clear()


def revalidate_model_artifact_identity(artifact: VerifiedModelArtifact) -> None:
    """Fail if metadata *or bytes* changed since cryptographic verification."""

    current_artifact = _file_identity(artifact.path, code="artifact_unreadable")
    current_manifest = _file_identity(artifact.manifest_path, code="manifest_unreadable")
    if (
        current_artifact != artifact.artifact_identity
        or current_manifest != artifact.manifest_identity
    ):
        raise ModelArtifactUnavailable(
            "artifact_identity_changed",
            "artifact or manifest changed after verification",
        )
    if (
        _sha256_file(artifact.path) != artifact.sha256
        or _sha256_file(artifact.manifest_path) != artifact.manifest_sha256
    ):
        raise ModelArtifactUnavailable(
            "artifact_content_changed",
            "artifact or manifest bytes changed after verification",
        )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        raise ModelArtifactUnavailable(
            "artifact_unreadable", "artifact bytes could not be read"
        ) from None
    return digest.hexdigest()


def _reject_external_onnx_data(path: Path, size: int) -> None:
    """Forbid mutable ONNX sidecars that are not covered by the artifact digest."""

    if size > _MAX_ONNX_PROTO_INSPECTION_BYTES:
        raise ModelArtifactUnavailable(
            "artifact_too_large_for_inspection",
            "ONNX exceeds the bounded self-contained-data inspection profile",
        )
    try:
        import onnx

        model = onnx.load_model(path, load_external_data=False)
    except Exception as exc:  # noqa: BLE001 - parser/library failures must fail closed
        raise ModelArtifactUnavailable(
            "artifact_uninspectable",
            "ONNX could not be parsed while verifying its self-contained data contract",
        ) from exc

    def walk(message: Any) -> None:
        descriptor = getattr(message, "DESCRIPTOR", None)
        if descriptor is not None and descriptor.full_name == "onnx.TensorProto":
            external = int(getattr(message, "data_location", 0)) == int(
                onnx.TensorProto.EXTERNAL
            ) or bool(getattr(message, "external_data", ()))
            if external:
                raise ModelArtifactUnavailable(
                    "external_data_forbidden",
                    "ONNX external-data sidecars are not allowed; package one self-contained file",
                )
        for field_descriptor, value in message.ListFields():
            if field_descriptor.type != field_descriptor.TYPE_MESSAGE:
                continue
            if field_descriptor.is_repeated:
                for child in value:
                    walk(child)
            else:
                walk(value)

    walk(model)


def _freeze_json(value: Any) -> Any:
    """Recursively freeze a validated JSON value for safe shared caching."""

    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    """Create a mutable defensive copy without exposing the cached receipt internals."""

    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


class _DuplicateManifestKey(ValueError):
    """Internal signal used by the JSON object-pairs hook."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for key, value in pairs:
        if key in parsed:
            raise _DuplicateManifestKey
        parsed[key] = value
    return parsed


def _bounded_string(
    value: object,
    *,
    max_chars: int = _MAX_TEXT_CHARS,
    ascii_only: bool = True,
) -> bool:
    return (
        isinstance(value, str)
        and value == value.strip()
        and 0 < len(value) <= max_chars
        and (not ascii_only or value.isascii())
        and all(character.isprintable() for character in value)
    )


def _require_exact_fields(
    raw: Mapping[str, Any],
    *,
    required: frozenset[str],
    allowed: frozenset[str],
    code: str = "manifest_invalid",
) -> None:
    fields = set(raw)
    if not required.issubset(fields) or not fields.issubset(allowed):
        raise ModelArtifactUnavailable(code, "object fields do not match schema")


def _validate_manifest_root(parsed: Mapping[str, Any]) -> None:
    _require_exact_fields(
        parsed,
        required=_ROOT_REQUIRED_FIELDS,
        allowed=_ROOT_ALLOWED_FIELDS,
    )
    snapshot_date = parsed.get("snapshot_date")
    if snapshot_date is not None:
        if not isinstance(snapshot_date, str) or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}", snapshot_date
        ):
            raise ModelArtifactUnavailable(
                "manifest_invalid", "snapshot_date must be a calendar date"
            )
        try:
            date.fromisoformat(snapshot_date)
        except ValueError:
            raise ModelArtifactUnavailable(
                "manifest_invalid", "snapshot_date must be a calendar date"
            ) from None
    artifacts = parsed.get("artifacts")
    if not isinstance(artifacts, list) or not 1 <= len(artifacts) <= _MAX_ARTIFACTS:
        raise ModelArtifactUnavailable(
            "manifest_invalid", "artifacts must be a non-empty bounded array"
        )


def _read_manifest(path: Path) -> tuple[dict[str, Any], str]:
    try:
        with path.open("rb") as handle:
            payload = handle.read(_MAX_MANIFEST_BYTES + 1)
    except OSError:
        raise ModelArtifactUnavailable(
            "manifest_unreadable", "manifest bytes could not be read"
        ) from None
    if len(payload) > _MAX_MANIFEST_BYTES:
        raise ModelArtifactUnavailable("manifest_too_large", "manifest exceeds size limit")
    try:
        parsed = json.loads(payload, object_pairs_hook=_reject_duplicate_keys)
    except _DuplicateManifestKey:
        raise ModelArtifactUnavailable(
            "manifest_duplicate_key", "manifest contains a duplicate JSON key"
        ) from None
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise ModelArtifactUnavailable("manifest_invalid", "manifest is not valid JSON") from None
    if not isinstance(parsed, dict):
        raise ModelArtifactUnavailable("manifest_invalid", "root must be a JSON object")
    schema_version = parsed.get("schema_version")
    if type(schema_version) is not int or schema_version != _SCHEMA_VERSION:
        raise ModelArtifactUnavailable(
            "schema_version_unsupported",
            f"schema_version must be exactly {_SCHEMA_VERSION}",
        )
    _validate_manifest_root(parsed)
    return parsed, hashlib.sha256(payload).hexdigest()


def _canonical_declared_artifact_path(value: object, manifest_root: Path) -> Path:
    if not _bounded_string(value, max_chars=_MAX_ARTIFACT_PATH_CHARS):
        raise ModelArtifactUnavailable("manifest_invalid", "artifact path is invalid")
    if not isinstance(value, str):
        raise ModelArtifactUnavailable("manifest_invalid", "artifact path is invalid")
    if "\\" in value:
        raise ModelArtifactUnavailable("manifest_invalid", "artifact path is not canonical")
    raw_parts = value.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise ModelArtifactUnavailable("manifest_invalid", "artifact path is not canonical")
    relative = PurePosixPath(value)
    if relative.is_absolute() or str(relative) != value:
        raise ModelArtifactUnavailable("manifest_invalid", "artifact path is not canonical")
    for part in raw_parts:
        stem = part.split(".", 1)[0].upper()
        if not _CANONICAL_PATH_PART_RE.fullmatch(part) or stem in _WINDOWS_RESERVED_PATH_STEMS:
            raise ModelArtifactUnavailable("manifest_invalid", "artifact path is not canonical")

    candidate = (manifest_root / Path(*relative.parts)).resolve()
    try:
        candidate.relative_to(manifest_root)
    except ValueError:
        raise ModelArtifactUnavailable(
            "artifact_outside_manifest", "artifact must remain inside the manifest directory"
        ) from None
    if candidate == manifest_root:
        raise ModelArtifactUnavailable("manifest_invalid", "artifact path is invalid")
    return candidate


def _validate_embedded_metadata(raw: object) -> None:
    if not isinstance(raw, dict) or not set(raw).issubset(_EMBEDDED_METADATA_FIELDS):
        raise ModelArtifactUnavailable(
            "manifest_invalid", "embedded metadata does not match schema"
        )
    if not all(_bounded_string(value, max_chars=512) for value in raw.values()):
        raise ModelArtifactUnavailable(
            "manifest_invalid", "embedded metadata contains an invalid value"
        )


def _validate_training_context(raw: object) -> None:
    if not isinstance(raw, dict):
        raise ModelArtifactUnavailable("manifest_invalid", "training context must be an object")
    _require_exact_fields(
        raw,
        required=_TRAINING_CONTEXT_FIELDS,
        allowed=_TRAINING_CONTEXT_FIELDS,
    )
    for field_name in ("project_commit", "dataset_commit", "dataset_tree"):
        value = raw.get(field_name)
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None:
            raise ModelArtifactUnavailable(
                "manifest_invalid", "training context contains an invalid Git object id"
            )
    for field_name in (
        "dataset_split_receipt_sha256",
        "phh_corpus_governance_receipt_sha256",
    ):
        value = raw.get(field_name)
        if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
            raise ModelArtifactUnavailable(
                "manifest_invalid", "training context contains an invalid receipt digest"
            )


def _validate_training_evidence_shape(raw: object) -> None:
    if not isinstance(raw, dict):
        raise ModelArtifactUnavailable(
            "training_evidence_invalid", "training evidence must be an object"
        )
    _require_exact_fields(
        raw,
        required=_TRAINING_EVIDENCE_FIELDS,
        allowed=_TRAINING_EVIDENCE_FIELDS,
        code="training_evidence_invalid",
    )
    for field_name in ("metrics_path", "trace_path"):
        if not _bounded_string(raw.get(field_name), max_chars=_MAX_ARTIFACT_PATH_CHARS):
            raise ModelArtifactUnavailable("training_evidence_invalid", "evidence path is invalid")
    for field_name in ("metrics_sha256", "trace_sha256"):
        value = raw.get(field_name)
        if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
            raise ModelArtifactUnavailable(
                "training_evidence_invalid", "evidence digest is invalid"
            )


def _read_strict_json_file(path: Path, *, code: str) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            payload = handle.read(_MAX_TRAINING_EVIDENCE_BYTES + 1)
    except OSError:
        raise ModelArtifactUnavailable(code, "training evidence is unreadable") from None
    if len(payload) > _MAX_TRAINING_EVIDENCE_BYTES:
        raise ModelArtifactUnavailable(code, "training evidence exceeds its size limit")
    try:
        parsed = json.loads(payload, object_pairs_hook=_reject_duplicate_keys)
    except (_DuplicateManifestKey, UnicodeDecodeError, ValueError, RecursionError):
        raise ModelArtifactUnavailable(code, "training evidence is not strict JSON") from None
    if not isinstance(parsed, dict):
        raise ModelArtifactUnavailable(code, "training evidence root must be an object")
    return parsed


def _verify_expert_training_support(
    entry: Mapping[str, Any], manifest_root: Path, artifact_sha256: str
) -> None:
    raw = entry.get("training_evidence")
    _validate_training_evidence_shape(raw)
    if not isinstance(raw, dict):
        raise ModelArtifactUnavailable(
            "training_evidence_invalid", "training evidence must be an object"
        )
    metrics_path = _canonical_declared_artifact_path(raw["metrics_path"], manifest_root)
    trace_path = _canonical_declared_artifact_path(raw["trace_path"], manifest_root)
    for path, digest_field in (
        (metrics_path, "metrics_sha256"),
        (trace_path, "trace_sha256"),
    ):
        if not path.is_file() or _sha256_file(path) != raw[digest_field]:
            raise ModelArtifactUnavailable(
                "training_evidence_mismatch", "training evidence file or digest does not match"
            )
    metrics = _read_strict_json_file(metrics_path, code="training_evidence_invalid")
    artifact_digests = metrics.get("artifact_sha256")
    metrics_onnx_sha = (
        artifact_digests.get("onnx") if isinstance(artifact_digests, dict) else artifact_digests
    )
    if metrics_onnx_sha != artifact_sha256:
        raise ModelArtifactUnavailable(
            "training_evidence_mismatch", "training evidence belongs to another artifact"
        )
    try:
        with trace_path.open("r", encoding="utf-8") as handle:
            configuration = json.loads(handle.readline(), object_pairs_hook=_reject_duplicate_keys)
            prepared = json.loads(handle.readline(), object_pairs_hook=_reject_duplicate_keys)
    except (OSError, UnicodeDecodeError, ValueError, RecursionError, _DuplicateManifestKey):
        raise ModelArtifactUnavailable(
            "training_evidence_invalid", "training trace header is invalid"
        ) from None
    counts = (
        prepared.get("optimization_training_class_counts") if isinstance(prepared, dict) else None
    )
    if (
        not isinstance(configuration, dict)
        or configuration.get("event") != "training_configuration"
        or not isinstance(prepared, dict)
        or prepared.get("event") != "dataset_prepared"
        or not isinstance(counts, list)
        or len(counts) != 10
        or any(type(count) is not int or count < 0 for count in counts)
    ):
        raise ModelArtifactUnavailable(
            "training_evidence_invalid", "training trace does not contain valid per-action counts"
        )
    source_binding = configuration.get("source_binding")
    if not isinstance(source_binding, str) or source_binding != metrics.get("source_binding"):
        raise ModelArtifactUnavailable(
            "training_evidence_mismatch", "metrics and trace source bindings differ"
        )
    supported = tuple(index for index, count in enumerate(counts) if count > 0)
    policy = entry.get("inference_policy")
    declared = tuple(policy.get("supported_action_indices", ())) if isinstance(policy, dict) else ()
    if declared != supported:
        raise ModelArtifactUnavailable(
            "expert_action_support_mismatch",
            "manifest action support must exactly match positive training counts",
        )


def _validate_expected_contract(entry: Mapping[str, Any]) -> None:
    inputs = entry.get("expected_inputs")
    outputs = entry.get("expected_outputs")
    if not isinstance(inputs, list) or not 1 <= len(inputs) <= 8:
        raise ModelArtifactUnavailable("manifest_invalid", "expected inputs are invalid")
    if not isinstance(outputs, list) or not 1 <= len(outputs) <= 8:
        raise ModelArtifactUnavailable("manifest_invalid", "expected outputs are invalid")
    for tensor in inputs:
        if not isinstance(tensor, dict):
            raise ModelArtifactUnavailable("manifest_invalid", "expected input is invalid")
        _require_exact_fields(
            tensor,
            required=frozenset({"dtype", "shape"}),
            allowed=frozenset({"dtype", "shape"}),
        )
        _declared_tensor(tensor, "expected input", allow_name=False)
    for tensor in outputs:
        if not isinstance(tensor, dict):
            raise ModelArtifactUnavailable("manifest_invalid", "expected output is invalid")
        _require_exact_fields(
            tensor,
            required=frozenset({"semantic", "shape"}),
            allowed=frozenset({"semantic", "shape"}),
        )
        if not _bounded_string(tensor.get("semantic"), max_chars=64):
            raise ModelArtifactUnavailable("manifest_invalid", "expected output is invalid")
        shape = tensor.get("shape")
        if (
            not isinstance(shape, list)
            or not 1 <= len(shape) <= _MAX_SHAPE_RANK
            or not all(_valid_declared_dim(dim) for dim in shape)
        ):
            raise ModelArtifactUnavailable("manifest_invalid", "expected output is invalid")


def _validate_manifest_entry_schema(
    entry: Mapping[str, Any], *, kind: ArtifactKind | None = None
) -> None:
    legacy = {"license_status", "lineage_status"}.intersection(entry)
    if legacy:
        raise ModelArtifactUnavailable(
            "governance_invalid", "legacy governance fields are forbidden"
        )
    state = entry.get("state")
    if not isinstance(state, str) or state not in _ARTIFACT_STATES:
        raise ModelArtifactUnavailable("state_invalid", "state is not a schema-v1 lifecycle value")
    if state == "missing":
        _require_exact_fields(
            entry,
            required=_MISSING_ENTRY_FIELDS,
            allowed=_MISSING_ENTRY_FIELDS,
        )
        if entry.get("installed") is not False or entry.get("sha256") is not None:
            raise ModelArtifactUnavailable(
                "manifest_invalid", "missing artifacts must be uninstalled and unhashed"
            )
        _validate_expected_contract(entry)
        _validate_governance_shape(entry)
        return

    allowed = _NONMISSING_ENTRY_FIELDS
    if kind is not None:
        allowed = (
            _BASE_ENTRY_FIELDS | _COMMON_OPTIONAL_ENTRY_FIELDS | _KIND_OPTIONAL_ENTRY_FIELDS[kind]
        )
    _require_exact_fields(entry, required=_BASE_ENTRY_FIELDS, allowed=allowed)
    if entry.get("installed") is not True:
        raise ModelArtifactUnavailable(
            "artifact_not_installed", "installed must be true for materialized artifacts"
        )
    declared_sha = entry.get("sha256")
    if not isinstance(declared_sha, str) or _SHA256_RE.fullmatch(declared_sha) is None:
        raise ModelArtifactUnavailable("sha256_invalid", "manifest sha256 must be lowercase hex")
    size_bytes = entry.get("size_bytes")
    if size_bytes is not None and (
        type(size_bytes) is not int or not 1 <= size_bytes <= _MAX_ARTIFACT_BYTES
    ):
        raise ModelArtifactUnavailable("manifest_invalid", "declared artifact size is invalid")
    producer = entry.get("producer")
    if producer is not None and (
        not isinstance(producer, str) or _SAFE_IDENTIFIER_RE.fullmatch(producer) is None
    ):
        raise ModelArtifactUnavailable("manifest_invalid", "producer is invalid")
    if "embedded_metadata" in entry:
        _validate_embedded_metadata(entry["embedded_metadata"])
    if "training_context" in entry:
        _validate_training_context(entry["training_context"])
    if "training_evidence" in entry:
        _validate_training_evidence_shape(entry["training_evidence"])
    if "inference_policy" in entry:
        _validate_inference_policy_shape(entry["inference_policy"])
    if "classes" in entry:
        classes = entry["classes"]
        if (
            not isinstance(classes, list)
            or len(classes) not in {52, 54}
            or not all(_bounded_string(name, max_chars=64) for name in classes)
            or len(set(classes)) != len(classes)
        ):
            raise ModelArtifactUnavailable("contract_invalid", "classes are invalid")
    _validate_governance_shape(entry)

    inputs = entry.get("inputs")
    outputs = entry.get("outputs")
    if not isinstance(inputs, list) or not 1 <= len(inputs) <= 8:
        raise ModelArtifactUnavailable("contract_invalid", "inputs must be a bounded array")
    if not isinstance(outputs, list) or not 1 <= len(outputs) <= 8:
        raise ModelArtifactUnavailable("contract_invalid", "outputs must be a bounded array")
    for tensor in (*inputs, *outputs):
        _declared_tensor(tensor, "tensor")

    if kind is None:
        kind = _infer_artifact_kind(entry)
        exact_fields = (
            _BASE_ENTRY_FIELDS | _COMMON_OPTIONAL_ENTRY_FIELDS | _KIND_OPTIONAL_ENTRY_FIELDS[kind]
        )
        _require_exact_fields(
            entry,
            required=_BASE_ENTRY_FIELDS,
            allowed=exact_fields,
        )
    if (
        kind == "expert"
        and entry.get("encoder_revision") == EXPERT_ENCODER_V2
        and entry.get("action_space_revision") == EXPERT_ACTION_SPACE_V2
    ):
        policy = entry.get("inference_policy")
        if (
            not isinstance(policy, dict)
            or policy.get("state") == "unapproved"
            or "training_evidence" not in entry
        ):
            raise ModelArtifactUnavailable(
                "expert_action_support_missing",
                "v2 Expert artifacts require approved, evidence-bound action support",
            )
        supported = policy.get("supported_action_indices")
        if not isinstance(supported, list) or not {0, 1}.issubset(supported):
            raise ModelArtifactUnavailable(
                "expert_action_support_unsafe",
                "v2 Expert support must include fold and check/call",
            )
    elif kind == "expert" and state != "promoted":
        policy = entry.get("inference_policy")
        supported = policy.get("supported_action_indices") if isinstance(policy, dict) else None
        if isinstance(supported, list) and any(
            type(index) is int and index >= 5 for index in supported
        ):
            raise ModelArtifactUnavailable(
                "policy_invalid", "legacy Expert support cannot exceed its five outputs"
            )
    if kind == "vision":
        if state in _APPROVED_STATES:
            _validate_promotion_receipt_shape(
                entry.get("promotion_receipt"), PROMOTION_PROFILE_REVISION
            )
        elif "promotion_receipt" in entry:
            raise ModelArtifactUnavailable(
                "promotion_evidence_invalid",
                "non-deployable vision artifacts cannot carry promotion evidence",
            )
    elif kind == "expert" and state == "promoted":
        if (
            entry.get("encoder_revision") != EXPERT_ENCODER_V2
            or entry.get("action_space_revision") != EXPERT_ACTION_SPACE_V2
        ):
            raise ModelArtifactUnavailable(
                "expert_contract_legacy",
                "promoted Expert artifacts require the seat/history-aware v2 contract",
            )
        _validate_promotion_receipt_shape(
            entry.get("promotion_receipt"), EXPERT_PROMOTION_PROFILE_REVISION
        )
    elif "promotion_receipt" in entry:
        raise ModelArtifactUnavailable(
            "promotion_profile_unsupported",
            "promotion evidence cannot authorize this model lifecycle or task",
        )
    if kind == "vision" and "classes" not in entry:
        raise ModelArtifactUnavailable("contract_mismatch", "vision classes are required")


def _validate_promotion_receipt_shape(raw: object, expected_profile: str) -> None:
    if not isinstance(raw, dict) or set(raw) != _PROMOTION_RECEIPT_FIELDS:
        raise ModelArtifactUnavailable(
            "promotion_evidence_missing",
            "approved/promoted artifacts require exact promotion evidence",
        )
    path = raw.get("path")
    if (
        not isinstance(path, str)
        or not path.endswith(".json")
        or path.startswith(("/", "\\"))
        or "\\" in path
    ):
        raise ModelArtifactUnavailable(
            "promotion_evidence_invalid", "promotion receipt path is invalid"
        )
    digest = raw.get("sha256")
    if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
        raise ModelArtifactUnavailable(
            "promotion_evidence_invalid", "promotion receipt digest is invalid"
        )
    contract_digest = raw.get("artifact_contract_sha256")
    if not isinstance(contract_digest, str) or _SHA256_RE.fullmatch(contract_digest) is None:
        raise ModelArtifactUnavailable(
            "promotion_evidence_invalid", "promotion contract digest is invalid"
        )
    if raw.get("profile_revision") != expected_profile:
        raise ModelArtifactUnavailable(
            "promotion_profile_unsupported", "promotion receipt profile is unsupported"
        )


def _verify_promotion_entry(
    entry: Mapping[str, Any], manifest_path: Path, artifact_sha256: str, kind: ArtifactKind
) -> None:
    raw = entry.get("promotion_receipt")
    expected_profile = (
        EXPERT_PROMOTION_PROFILE_REVISION if kind == "expert" else PROMOTION_PROFILE_REVISION
    )
    _validate_promotion_receipt_shape(raw, expected_profile)
    if not isinstance(raw, dict):  # pragma: no cover - narrowed by validator
        raise ModelArtifactUnavailable("promotion_evidence_invalid", "receipt is invalid")
    receipt_path = _canonical_declared_artifact_path(raw["path"], manifest_path.parent.resolve())
    contract_digest = promotion_contract_sha256(entry)
    if raw["artifact_contract_sha256"] != contract_digest:
        raise ModelArtifactUnavailable(
            "promotion_evidence_invalid", "manifest contract differs from promotion evidence"
        )
    try:
        if kind == "expert":
            policy = _manifest_inference_policy(entry)
            verify_expert_promotion_receipt(
                receipt_path,
                expected_sha256=raw["sha256"],
                artifact_sha256=artifact_sha256,
                artifact_contract_sha256=contract_digest,
                decision_rule=policy.decision_rule,
            )
        else:
            verify_promotion_receipt(
                receipt_path,
                expected_sha256=raw["sha256"],
                artifact_sha256=artifact_sha256,
                artifact_contract_sha256=contract_digest,
            )
    except (PromotionEvidenceError, ExpertPromotionEvidenceError) as exc:
        raise ModelArtifactUnavailable(
            "promotion_evidence_invalid", "scientific receipt failed verification"
        ) from exc


def _manifest_entry(
    manifest: Mapping[str, Any],
    manifest_path: Path,
    artifact_path: Path,
    kind: ArtifactKind,
) -> dict[str, Any]:
    artifacts = manifest["artifacts"]
    if not isinstance(artifacts, list):
        raise ModelArtifactUnavailable("manifest_invalid", "artifacts must be a list")
    manifest_root = manifest_path.parent.resolve()
    wanted = artifact_path.resolve()
    try:
        wanted.relative_to(manifest_root)
    except ValueError:
        raise ModelArtifactUnavailable(
            "artifact_outside_manifest", "artifact must remain inside the manifest directory"
        ) from None

    matches: list[dict[str, Any]] = []
    declared_identities: set[str] = set()
    for raw in artifacts:
        if not isinstance(raw, dict):
            raise ModelArtifactUnavailable("manifest_invalid", "artifact entry must be an object")
        candidate = _canonical_declared_artifact_path(raw.get("path"), manifest_root)
        _validate_manifest_entry_schema(raw, kind=kind if candidate == wanted else None)
        identity = os.path.normcase(str(candidate))
        if identity in declared_identities:
            raise ModelArtifactUnavailable(
                "artifact_ambiguous", "manifest contains duplicate artifact paths"
            )
        declared_identities.add(identity)
        if candidate == wanted:
            matches.append(raw)
    if not matches:
        raise ModelArtifactUnavailable(
            "artifact_not_declared", "artifact has no matching manifest entry"
        )
    if len(matches) != 1:
        raise ModelArtifactUnavailable("artifact_ambiguous", "artifact is declared more than once")
    return matches[0]


def _normalized_dtype(value: object) -> str:
    if not isinstance(value, str):
        return ""
    normalized = value.strip().lower().replace(" ", "")
    aliases = {
        "float": "float32",
        "tensor(float)": "float32",
        "tensor(float32)": "float32",
    }
    return aliases.get(normalized, normalized)


def _valid_declared_dim(value: object) -> bool:
    return (type(value) is int and 0 < value <= 2_147_483_647) or (
        isinstance(value, str)
        and len(value) <= _MAX_SYMBOLIC_DIM_CHARS
        and _SYMBOLIC_DIM_RE.fullmatch(value) is not None
    )


def _shape_matches_rule(shape: Sequence[object], option: tuple[ShapeDim, ...]) -> bool:
    if len(shape) != len(option):
        return False
    for actual, expected in zip(shape, option, strict=True):
        if isinstance(expected, int):
            if actual != expected:
                return False
        elif not _valid_declared_dim(actual):
            return False
    return True


def _declared_tensor(raw: object, label: str, *, allow_name: bool = True) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ModelArtifactUnavailable("contract_invalid", f"{label} must be an object")
    allowed = frozenset({"name", "dtype", "shape"}) if allow_name else frozenset({"dtype", "shape"})
    _require_exact_fields(
        raw,
        required=frozenset({"dtype", "shape"}),
        allowed=allowed,
        code="contract_invalid",
    )
    name = raw.get("name")
    if name is not None and not _bounded_string(name, max_chars=128):
        raise ModelArtifactUnavailable("contract_invalid", f"{label}.name is invalid")
    shape = raw.get("shape")
    if (
        not isinstance(shape, list)
        or not 1 <= len(shape) <= _MAX_SHAPE_RANK
        or not all(_valid_declared_dim(dim) for dim in shape)
    ):
        raise ModelArtifactUnavailable("contract_invalid", f"{label}.shape is invalid")
    dtype = raw.get("dtype")
    if not _bounded_string(dtype, max_chars=64) or not _normalized_dtype(dtype):
        raise ModelArtifactUnavailable("contract_invalid", f"{label}.dtype is required")
    return raw


def _validate_declared_tensors(
    raw_tensors: object, rules: tuple[_TensorRule, ...], label: str
) -> tuple[dict[str, Any], ...]:
    if not isinstance(raw_tensors, list) or len(raw_tensors) != len(rules):
        raise ModelArtifactUnavailable(
            "contract_mismatch", f"{label} must contain exactly {len(rules)} tensor(s)"
        )
    declared: list[dict[str, Any]] = []
    for index, (raw, rule) in enumerate(zip(raw_tensors, rules, strict=True)):
        tensor = _declared_tensor(raw, f"{label}[{index}]")
        if rule.name is not None and tensor.get("name") != rule.name:
            raise ModelArtifactUnavailable(
                "contract_mismatch", f"{label}[{index}].name does not match the contract"
            )
        if _normalized_dtype(tensor.get("dtype")) != rule.dtype:
            raise ModelArtifactUnavailable(
                "contract_mismatch", f"{label}[{index}].dtype does not match the contract"
            )
        shape = tensor["shape"]
        if not any(_shape_matches_rule(shape, option) for option in rule.shapes):
            raise ModelArtifactUnavailable(
                "contract_mismatch", f"{label}[{index}].shape does not match the contract"
            )
        declared.append(tensor)
    return tuple(declared)


def _validate_declared_contract(entry: Mapping[str, Any], kind: ArtifactKind) -> None:
    rule = _CONTRACTS[kind]
    if kind == "expert":
        encoder_revision = entry.get("encoder_revision")
        action_revision = entry.get("action_space_revision")
        if encoder_revision is None and action_revision is None:
            if entry.get("state") == "promoted":
                raise ModelArtifactUnavailable(
                    "expert_contract_legacy",
                    "promoted Expert artifacts cannot use the legacy 121x5 contract",
                )
            rule = _EXPERT_V1_CONTRACT
        elif encoder_revision == EXPERT_ENCODER_V2 and action_revision == EXPERT_ACTION_SPACE_V2:
            rule = _EXPERT_V2_CONTRACT
        else:
            raise ModelArtifactUnavailable(
                "contract_mismatch",
                "Expert encoder and action-space revisions must form one supported pair",
            )
    _validate_declared_tensors(entry.get("inputs"), rule.inputs, "inputs")
    _validate_declared_tensors(entry.get("outputs"), rule.outputs, "outputs")
    if rule.class_counts:
        classes = entry.get("classes")
        if (
            not isinstance(classes, list)
            or len(classes) not in rule.class_counts
            or not all(_bounded_string(name, max_chars=64) for name in classes)
            or len(set(classes)) != len(classes)
        ):
            raise ModelArtifactUnavailable(
                "contract_mismatch", "classes must be a unique 52- or 54-name list"
            )


def _infer_artifact_kind(entry: Mapping[str, Any]) -> ArtifactKind:
    matches: list[ArtifactKind] = []
    for candidate in _CONTRACTS:
        try:
            _validate_declared_contract(entry, candidate)
        except ModelArtifactUnavailable:
            continue
        matches.append(candidate)
    if len(matches) != 1:
        raise ModelArtifactUnavailable(
            "manifest_invalid", "artifact contract does not identify exactly one model kind"
        )
    return matches[0]


def _valid_governance_reference(value: object) -> bool:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or len(value) > 2048
        or not value.isascii()
    ):
        return False
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return False
    if parsed.scheme == "https":
        if (
            hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or port not in (None, 443)
            or parsed.query
            or parsed.fragment
            or not parsed.path.startswith("/")
            or parsed.path in ("", "/")
            or ".." in parsed.path.split("/")
        ):
            return False
        host = hostname.lower()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and (
            not address.is_global
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            return False
        labels = host.split(".")
        return (
            len(host) <= 253
            and len(labels) >= 2
            and all(_PUBLIC_HOST_LABEL_RE.fullmatch(label) for label in labels)
        )
    if parsed.scheme == "urn":
        return (
            not parsed.netloc
            and not parsed.query
            and not parsed.fragment
            and bool(_URN_RE.fullmatch(value))
        )
    return False


def _governance_subject(
    entry: Mapping[str, Any], subject: str, *, require_verified: bool
) -> Mapping[str, Any]:
    governance = entry.get("governance")
    if not isinstance(governance, dict) or set(governance) != {"license", "lineage"}:
        raise ModelArtifactUnavailable(
            "governance_invalid", "governance must contain exactly license and lineage"
        )
    raw = governance.get(subject)
    if not isinstance(raw, dict) or set(raw) != {"status", "id", "reference"}:
        raise ModelArtifactUnavailable(
            "governance_invalid",
            f"governance.{subject} must contain exactly status, id and reference",
        )
    status = raw.get("status")
    if not isinstance(status, str) or status not in _GOVERNANCE_STATUSES:
        raise ModelArtifactUnavailable(
            "governance_invalid",
            f"governance.{subject}.status must be verified or unresolved",
        )
    identifier = raw.get("id")
    reference = raw.get("reference")
    if status == "unresolved":
        if identifier is not None or reference is not None:
            raise ModelArtifactUnavailable(
                "governance_invalid",
                f"unresolved governance.{subject} must use null id and reference",
            )
        if require_verified:
            raise ModelArtifactUnavailable("governance_unresolved", f"{subject} is unresolved")
        return {"status": status, "id": None, "reference": None}
    if not isinstance(identifier, str) or not _GOVERNANCE_ID_RE.fullmatch(identifier):
        raise ModelArtifactUnavailable("governance_invalid", f"governance.{subject}.id is invalid")
    normalized = identifier.lower().replace("-", "_")
    if normalized.startswith(_UNRESOLVED_PREFIXES) or normalized in {"denied", "fabricated"}:
        raise ModelArtifactUnavailable(
            "governance_invalid", f"governance.{subject}.id is not a resolved identifier"
        )
    if not isinstance(reference, str) or not _valid_governance_reference(reference):
        raise ModelArtifactUnavailable(
            "governance_invalid",
            f"governance.{subject}.reference must be an absolute HTTPS URI or URN",
        )
    return {"status": status, "id": identifier, "reference": reference}


def _validate_governance_shape(entry: Mapping[str, Any]) -> None:
    _governance_subject(entry, "license", require_verified=False)
    _governance_subject(entry, "lineage", require_verified=False)


def _validate_governance(entry: Mapping[str, Any]) -> None:
    legacy = {"license_status", "lineage_status"}.intersection(entry)
    if legacy:
        raise ModelArtifactUnavailable(
            "governance_invalid",
            "legacy governance fields are forbidden",
        )
    _governance_subject(entry, "license", require_verified=True)
    _governance_subject(entry, "lineage", require_verified=True)


def _policy_number(raw: Mapping[str, Any], name: str, *, lower: float, upper: float) -> float:
    value = raw.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ModelArtifactUnavailable("policy_invalid", f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or not lower <= result <= upper:
        raise ModelArtifactUnavailable("policy_invalid", f"{name} is outside its safe range")
    return result


def _validate_inference_policy_shape(raw: object) -> None:
    if not isinstance(raw, dict):
        raise ModelArtifactUnavailable("policy_invalid", "inference_policy must be an object")
    _require_exact_fields(
        raw,
        required=frozenset({"state"}),
        allowed=_INFERENCE_POLICY_FIELDS,
        code="policy_invalid",
    )
    state = raw.get("state")
    if not isinstance(state, str) or state not in _POLICY_STATES:
        raise ModelArtifactUnavailable(
            "policy_invalid",
            "inference_policy.state must be approved, promoted or unapproved",
        )
    numeric_fields = _INFERENCE_POLICY_FIELDS - {
        "state",
        "decision_rule",
        "supported_action_indices",
    }
    if state != "unapproved" and not numeric_fields.issubset(raw):
        raise ModelArtifactUnavailable("policy_invalid", "approved inference policy is incomplete")
    if "temperature" in raw:
        _policy_number(raw, "temperature", lower=0.0, upper=10.0)
    if "min_prob_ratio" in raw:
        _policy_number(raw, "min_prob_ratio", lower=0.0, upper=1.0)
    if "sizing_jitter" in raw:
        _policy_number(raw, "sizing_jitter", lower=0.0, upper=1.0)
    supported = raw.get("supported_action_indices")
    if state != "unapproved":
        if (
            not isinstance(supported, list)
            or not supported
            or any(type(index) is not int or not 0 <= index < 10 for index in supported)
            or supported != sorted(set(supported))
        ):
            raise ModelArtifactUnavailable(
                "policy_invalid",
                "supported_action_indices must be a non-empty sorted unique integer subset of [0, 9]",
            )
    elif supported is not None and (
        not isinstance(supported, list) or any(type(index) is not int for index in supported)
    ):
        raise ModelArtifactUnavailable("policy_invalid", "unsupported policy metadata is invalid")
    decision_rule = raw.get("decision_rule", "sampled")
    if not isinstance(decision_rule, str) or decision_rule not in _DECISION_RULES:
        raise ModelArtifactUnavailable("policy_invalid", "decision_rule must be modal or sampled")


def _manifest_inference_policy(entry: Mapping[str, Any]) -> InferencePolicy:
    raw = entry.get("inference_policy")
    if raw is None:
        return InferencePolicy()
    _validate_inference_policy_shape(raw)
    if not isinstance(raw, dict):
        raise ModelArtifactUnavailable("policy_invalid", "inference_policy must be an object")
    state = raw.get("state")
    if state == "unapproved":
        return InferencePolicy()

    return InferencePolicy(
        decision_rule=raw.get("decision_rule", "sampled"),
        temperature=_policy_number(raw, "temperature", lower=0.0, upper=10.0),
        min_prob_ratio=_policy_number(raw, "min_prob_ratio", lower=0.0, upper=1.0),
        sizing_jitter=_policy_number(raw, "sizing_jitter", lower=0.0, upper=1.0),
        supported_action_indices=tuple(raw["supported_action_indices"]),
        source="manifest",
    )


def _verify_model_artifact(
    model_path: str | Path,
    kind: ArtifactKind,
    *,
    manifest_path: str | Path | None = None,
    usage: ArtifactUsage,
) -> VerifiedModelArtifact:
    """Common verifier with a thread-safe, identity-invalidated success cache."""

    path = Path(model_path)
    if not path.is_file():
        raise ModelArtifactUnavailable("artifact_missing", "artifact file does not exist")
    resolved_manifest = (
        Path(manifest_path) if manifest_path is not None else model_manifest_path(path)
    )
    canonical_path = path.resolve()
    canonical_manifest = resolved_manifest.resolve()
    cache_key = (usage, kind, str(canonical_path), str(canonical_manifest))

    # Hold the lock through hashing so concurrent first users cannot hash the same
    # large model repeatedly.  Only successful receipts enter the cache.
    with _RECEIPT_CACHE_LOCK:
        artifact_before = _file_identity(canonical_path, code="artifact_unreadable")
        manifest_before = _file_identity(canonical_manifest, code="manifest_unreadable")
        if artifact_before.size > _MAX_ARTIFACT_BYTES:
            raise ModelArtifactUnavailable(
                "artifact_too_large", "artifact exceeds the verification size limit"
            )
        cached = _RECEIPT_CACHE.get(cache_key)
        if (
            cached is not None
            and cached.artifact_identity == artifact_before
            and cached.manifest_identity == manifest_before
        ):
            artifact_hash = _sha256_file(canonical_path)
            manifest_hash = _sha256_file(canonical_manifest)
            if (
                artifact_hash == cached.receipt.sha256
                and manifest_hash == cached.receipt.manifest_sha256
            ):
                if usage == "deployment" and kind in {"vision", "expert"}:
                    _verify_promotion_entry(
                        cached.receipt.entry, canonical_manifest, artifact_hash, kind
                    )
                return cached.receipt
        _RECEIPT_CACHE.pop(cache_key, None)

        manifest, manifest_digest = _read_manifest(canonical_manifest)
        entry = _manifest_entry(manifest, canonical_manifest, canonical_path, kind)

        state = entry.get("state")
        if not isinstance(state, str) or state not in _ARTIFACT_STATES:
            raise ModelArtifactUnavailable(
                "state_invalid", "state is not a schema-v1 lifecycle value"
            )
        expected_states = (
            (frozenset({"promoted"}) if kind == "expert" else _APPROVED_STATES)
            if usage == "deployment"
            else frozenset({"candidate"})
        )
        if state not in expected_states:
            expected = "approved/promoted" if usage == "deployment" else "candidate"
            raise ModelArtifactUnavailable(
                "state_not_approved" if usage == "deployment" else "state_not_candidate",
                f"state must be {expected} for {usage}",
            )
        _validate_governance(entry)

        declared_sha = entry.get("sha256")
        if not isinstance(declared_sha, str) or not _SHA256_RE.fullmatch(declared_sha):
            raise ModelArtifactUnavailable("sha256_invalid", "manifest sha256 must be 64 hex chars")
        declared_size = entry.get("size_bytes")
        if declared_size is not None and declared_size != artifact_before.size:
            raise ModelArtifactUnavailable(
                "artifact_size_mismatch", "artifact size differs from the manifest"
            )
        actual_sha = _sha256_file(canonical_path)
        if actual_sha != declared_sha:
            raise ModelArtifactUnavailable(
                "sha256_mismatch", "artifact digest differs from the manifest"
            )
        _reject_external_onnx_data(canonical_path, artifact_before.size)
        if kind == "expert" and entry.get("encoder_revision") == EXPERT_ENCODER_V2:
            _verify_expert_training_support(entry, canonical_manifest.parent, actual_sha)
        if usage == "deployment" and kind in {"vision", "expert"}:
            _verify_promotion_entry(entry, canonical_manifest, actual_sha, kind)

        _validate_declared_contract(entry, kind)
        policy = _manifest_inference_policy(entry)
        artifact_after = _file_identity(canonical_path, code="artifact_unreadable")
        manifest_after = _file_identity(canonical_manifest, code="manifest_unreadable")
        if artifact_after != artifact_before or manifest_after != manifest_before:
            raise ModelArtifactUnavailable(
                "artifact_changed_during_verification",
                "artifact or manifest changed while it was being verified",
            )
        receipt = VerifiedModelArtifact(
            path=canonical_path,
            manifest_path=canonical_manifest,
            sha256=actual_sha,
            manifest_sha256=manifest_digest,
            kind=kind,
            usage=usage,
            _entry=_freeze_json(entry),
            inference_policy=policy,
            artifact_identity=artifact_after,
            manifest_identity=manifest_after,
        )
        _RECEIPT_CACHE[cache_key] = _CachedReceipt(
            receipt=receipt,
            artifact_identity=artifact_after,
            manifest_identity=manifest_after,
        )
        return receipt


def verify_model_artifact(
    model_path: str | Path,
    kind: ArtifactKind,
    *,
    manifest_path: str | Path | None = None,
) -> VerifiedModelArtifact:
    """Verify an approved/promoted artifact for deployment and runtime loading."""

    return _verify_model_artifact(
        model_path,
        kind,
        manifest_path=manifest_path,
        usage="deployment",
    )


def verify_evaluation_candidate(
    model_path: str | Path,
    kind: ArtifactKind,
    *,
    manifest_path: str | Path | None = None,
) -> VerifiedModelArtifact:
    """Verify a candidate solely for explicit offline evaluation.

    This lane intentionally rejects approved/promoted artifacts.  Conversely,
    :func:`verify_model_artifact` rejects candidates, so evaluation cannot silently
    mutate deployment availability or the bot factory's level registry.
    """

    return _verify_model_artifact(
        model_path,
        kind,
        manifest_path=manifest_path,
        usage="evaluation",
    )


def model_artifact_available(
    model_path: str | Path,
    kind: ArtifactKind,
    *,
    manifest_path: str | Path | None = None,
) -> bool:
    """Cheap public semantics: unavailable on every verification failure."""

    try:
        verify_model_artifact(model_path, kind, manifest_path=manifest_path)
    except ModelArtifactUnavailable:
        return False
    return True


def _runtime_tensor(node: object) -> dict[str, Any]:
    shape = getattr(node, "shape", None)
    if not isinstance(shape, (list, tuple)):
        raise ModelArtifactUnavailable("runtime_contract_mismatch", "runtime tensor shape missing")
    return {
        "name": getattr(node, "name", None),
        "dtype": getattr(node, "type", None),
        "shape": list(shape),
    }


def _runtime_dim_matches(declared: object, actual: object) -> bool:
    if isinstance(declared, int):
        return actual == declared
    return actual is None or _valid_declared_dim(actual)


def _validate_runtime_side(
    declared_raw: object, runtime_nodes: Sequence[object], label: str
) -> None:
    if not isinstance(declared_raw, list) or len(declared_raw) != len(runtime_nodes):
        raise ModelArtifactUnavailable(
            "runtime_contract_mismatch", f"runtime {label} count differs from manifest"
        )
    for index, (declared_obj, node) in enumerate(zip(declared_raw, runtime_nodes, strict=True)):
        declared = _declared_tensor(declared_obj, f"{label}[{index}]")
        actual = _runtime_tensor(node)
        declared_name = declared.get("name")
        if declared_name is not None and actual["name"] != declared_name:
            raise ModelArtifactUnavailable(
                "runtime_contract_mismatch",
                f"runtime {label}[{index}] name differs from the manifest",
            )
        if _normalized_dtype(actual["dtype"]) != _normalized_dtype(declared.get("dtype")):
            raise ModelArtifactUnavailable(
                "runtime_contract_mismatch", f"runtime {label}[{index}] dtype differs"
            )
        declared_shape = declared["shape"]
        actual_shape = actual["shape"]
        if len(declared_shape) != len(actual_shape) or not all(
            _runtime_dim_matches(expected, got)
            for expected, got in zip(declared_shape, actual_shape, strict=True)
        ):
            raise ModelArtifactUnavailable(
                "runtime_contract_mismatch",
                f"runtime {label}[{index}] shape differs from the manifest",
            )


def verify_runtime_contract(
    artifact: VerifiedModelArtifact,
    inputs: Sequence[object],
    outputs: Sequence[object],
) -> None:
    """Cross-check the loaded runtime graph against the hash-pinned declaration."""

    _validate_runtime_side(artifact.entry.get("inputs"), inputs, "inputs")
    _validate_runtime_side(artifact.entry.get("outputs"), outputs, "outputs")
