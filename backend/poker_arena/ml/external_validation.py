"""Fail-closed scientific gate for promotion of vision models.

The gate binds one model digest to an authorized dataset manifest and to raw
predictions over a genuinely external split.  It never trains, downloads, or
promotes a model.  A successful, hash-pinned receipt is the only evidence that
the model-artifact lifecycle accepts for a deployable vision artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import platform
import re
import stat
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from statistics import fmean
from typing import Any, Final

from PIL import Image, UnidentifiedImageError

from poker_arena.ml.data_manifest import validate_manifest

SCHEMA_VERSION: Final = 2
PROFILE_REVISION: Final = "poker-arena-external-vision-v2-2026-08-07"
PIPELINE_REVISION: Final = "poker-arena-strict-f2-exact-state-v2-2026-08-07"
EXTERNAL_SPLIT: Final = "external-test"
MAX_JSON_BYTES: Final = 16 * 1024 * 1024
MAX_RECEIPT_BYTES: Final = 2 * 1024 * 1024
MAX_SAMPLE_SNAPSHOT_BYTES: Final = 128 * 1024 * 1024
MAX_RECORDS: Final = 100_000
MAX_NEAR_DUPLICATE_CANDIDATES: Final = 4_096
MAX_IMAGE_DIMENSION: Final = 8_192
MAX_IMAGE_PIXELS: Final = 16_000_000
NEAR_DUPLICATE_HAMMING: Final = 4
MIN_TOTAL: Final = 200
MIN_SUBGROUP: Final = 40
MIN_ACCEPTED: Final = 142
MIN_SOURCES: Final = 3
MIN_CLIENTS: Final = 3
MIN_THEMES: Final = 2
MIN_DECKS: Final = 2
MIN_SESSIONS: Final = 20
MIN_RESOLUTIONS: Final = 3
MIN_EXACT_LCB: Final = 0.90
MIN_SUBGROUP_EXACT_LCB: Final = 0.80
MAX_FALSE_ACCEPT_UCB: Final = 0.05
MAX_ECE: Final = 0.05
MAX_BRIER: Final = 0.05
MAX_LATENCY_P95_MS: Final = 1_000.0

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_ID_RE = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?")
_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp"})
_POLICY: Final[dict[str, int | float | str]] = {
    "external_split": EXTERNAL_SPLIT,
    "near_duplicate_hamming": NEAR_DUPLICATE_HAMMING,
    "min_total": MIN_TOTAL,
    "min_subgroup": MIN_SUBGROUP,
    "min_accepted": MIN_ACCEPTED,
    "min_sources": MIN_SOURCES,
    "min_clients": MIN_CLIENTS,
    "min_themes": MIN_THEMES,
    "min_decks": MIN_DECKS,
    "min_sessions": MIN_SESSIONS,
    "min_resolutions": MIN_RESOLUTIONS,
    "min_exact_lcb": MIN_EXACT_LCB,
    "min_subgroup_exact_lcb": MIN_SUBGROUP_EXACT_LCB,
    "max_false_accept_ucb": MAX_FALSE_ACCEPT_UCB,
    "max_ece": MAX_ECE,
    "max_brier": MAX_BRIER,
    "max_latency_p95_ms": MAX_LATENCY_P95_MS,
    "min_annotators": 2,
    "annotation_adjudication": "required-for-disagreement",
    "annotation_blind_to_model": "required",
}
_INFERENCE_CONFIG: Final[dict[str, bool | float | str]] = {
    "engine": "F2-onnx",
    "ocr_numbers": True,
    "deep_stacks": False,
    "strict": True,
    "abstain_below": 0.85,
}


def execution_environment() -> dict[str, bool | int | str]:
    """Return the bounded environment disclosure required for latency evidence."""

    def package_version(name: str) -> str:
        try:
            return version(name)
        except PackageNotFoundError:
            return "not-installed"

    return {
        "operating_system": platform.system() or "unknown",
        "os_release": platform.release() or "unknown",
        "machine": platform.machine() or "unknown",
        "logical_cpu_count": os.cpu_count() or 1,
        "python": platform.python_version(),
        "pillow": package_version("Pillow"),
        "onnxruntime": package_version("onnxruntime"),
        "execution_provider": "CPUExecutionProvider",
        "session_lifecycle": "single-persistent-session",
        "measurement_scope": "decode-preprocess-inference-postprocess-sanity",
        "warmup_discarded": False,
    }


class ScientificGateError(RuntimeError):
    """The gate could not safely evaluate the supplied evidence."""


class PromotionEvidenceError(RuntimeError):
    """A promotion receipt is absent, malformed, stale, or below policy."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"promotion evidence rejected [{code}]: {detail}")


class _DuplicateKey(ValueError):
    pass


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def current_pipeline_binding() -> dict[str, str]:
    """Bind evidence to the evaluator, deployed path, configuration and lockfile."""

    backend_root = Path(__file__).resolve().parents[2]
    source_paths = [
        Path(__file__).resolve(),
        backend_root / "poker_arena" / "api" / "app.py",
        backend_root / "poker_arena" / "vision" / "localize_read.py",
        backend_root / "poker_arena" / "vision" / "onnx_recognize.py",
        backend_root / "poker_arena" / "vision" / "ocr.py",
        backend_root / "poker_arena" / "vision" / "recognize.py",
        backend_root / "poker_arena" / "vision" / "sanity.py",
        backend_root / "poker_arena" / "vision" / "seats.py",
    ]
    digest = hashlib.sha256()
    for path in sorted(source_paths, key=lambda item: item.as_posix()):
        relative = path.relative_to(backend_root).as_posix().encode()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(_sha256_file(path, limit=MAX_JSON_BYTES)))
    lock_path = backend_root / "uv.lock"
    return {
        "revision": PIPELINE_REVISION,
        "source_receipt_sha256": digest.hexdigest(),
        "inference_config_sha256": _canonical_sha256(_INFERENCE_CONFIG),
        "dependency_lock_sha256": _sha256_file(lock_path, limit=MAX_JSON_BYTES),
    }


@dataclass(frozen=True, slots=True)
class VerifiedPromotionEvidence:
    path: Path
    sha256: str
    artifact_sha256: str
    dataset_manifest_sha256: str
    observations_sha256: str


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey
        result[key] = value
    return result


def _load_json(path: Path, *, limit: int) -> tuple[dict[str, Any], bytes]:
    """Read a bounded regular file snapshot and reject links/replacements."""

    try:
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise ScientificGateError("evidence path is not a regular file")
        if before.st_size > limit:
            raise ScientificGateError("evidence file exceeds the bounded profile")
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise ScientificGateError("evidence file changed before reading")
            payload = handle.read(limit + 1)
            after_fd = os.fstat(handle.fileno())
        after = path.lstat()
    except OSError as exc:
        raise ScientificGateError("evidence file is unavailable") from exc
    if len(payload) > limit:
        raise ScientificGateError("evidence file exceeds the bounded profile")
    fingerprint = lambda value: (  # noqa: E731 - compact immutable snapshot comparison
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )
    if fingerprint(before) != fingerprint(opened) or fingerprint(opened) != fingerprint(after_fd):
        raise ScientificGateError("evidence file changed while reading")
    if fingerprint(after_fd) != fingerprint(after):
        raise ScientificGateError("evidence path changed while reading")
    try:
        value = json.loads(
            payload,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, _DuplicateKey) as exc:
        raise ScientificGateError("evidence is not canonical finite JSON") from exc
    if not isinstance(value, dict):
        raise ScientificGateError("evidence root must be an object")
    return value, payload


def _sample_snapshot(path: Path, *, expected_sha256: str, limit: int) -> bytes:
    """Capture one stable, hash-verified descriptor snapshot for later consumption."""

    if _SHA256_RE.fullmatch(expected_sha256) is None:
        raise ScientificGateError("sample digest is invalid")
    try:
        before = path.lstat()
        attributes = int(getattr(before, "st_file_attributes", 0))
        if (
            stat.S_ISLNK(before.st_mode)
            or attributes & 0x400  # FILE_ATTRIBUTE_REPARSE_POINT
            or not stat.S_ISREG(before.st_mode)
        ):
            raise ScientificGateError("sample is not a regular non-reparse file")
        if before.st_size > limit:
            raise ScientificGateError("sample exceeds the snapshot size profile")
        digest = hashlib.sha256()
        chunks: list[bytes] = []
        total = 0
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                total += len(chunk)
                if total > limit:
                    raise ScientificGateError("sample exceeds the snapshot size profile")
                digest.update(chunk)
                chunks.append(chunk)
            after_fd = os.fstat(handle.fileno())
        after = path.lstat()
    except OSError as exc:
        raise ScientificGateError("sample could not be captured safely") from exc
    fingerprint = lambda value: (  # noqa: E731 - descriptor/path identity comparison
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )
    if (
        fingerprint(before) != fingerprint(opened)
        or fingerprint(opened) != fingerprint(after_fd)
        or fingerprint(after_fd) != fingerprint(after)
        or total != after.st_size
    ):
        raise ScientificGateError("sample changed while its snapshot was captured")
    if digest.hexdigest() != expected_sha256:
        raise ScientificGateError("sample digest differs from the validated manifest")
    return b"".join(chunks)


def _exact_fields(value: object, required: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != required:
        raise ScientificGateError(f"{label} has an unsupported schema")
    return value


def _sha256_file(path: Path, *, limit: int = 16 * 1024 * 1024 * 1024) -> str:
    try:
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise ScientificGateError("artifact is not a regular file")
        if before.st_size > limit:
            raise ScientificGateError("artifact exceeds the bounded profile")
        digest = hashlib.sha256()
        total = 0
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                total += len(chunk)
                if total > limit:
                    raise ScientificGateError("artifact exceeds the bounded profile")
                digest.update(chunk)
            after_fd = os.fstat(handle.fileno())
        after = path.lstat()
    except OSError as exc:
        raise ScientificGateError("artifact is unavailable") from exc
    identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)  # noqa: E731
    if identity(before) != identity(opened) or identity(opened) != identity(after_fd):
        raise ScientificGateError("artifact changed while hashing")
    if identity(after_fd) != identity(after) or total != after.st_size:
        raise ScientificGateError("artifact path changed while hashing")
    return digest.hexdigest()


def _safe_manifest_snapshot(path: Path, expected_sha256: str) -> dict[str, Any]:
    data, payload = _load_json(path, limit=MAX_JSON_BYTES)
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise ScientificGateError("dataset manifest changed after validation")
    return data


def _safe_sample_path(root: Path, relative: object) -> Path:
    if not isinstance(relative, str):
        raise ScientificGateError("dataset sample path is invalid")
    candidate = root.joinpath(*relative.split("/"))
    try:
        resolved_root = root.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise ScientificGateError("dataset sample escaped its authorized root") from exc
    return resolved


def _truth(payload: bytes) -> dict[str, Any]:
    if len(payload) > 64 * 1024:
        raise ScientificGateError("ground truth exceeds the bounded profile")
    try:
        raw = json.loads(
            payload,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, _DuplicateKey) as exc:
        raise ScientificGateError("ground truth is not canonical finite JSON") from exc
    if not isinstance(raw, dict):
        raise ScientificGateError("ground truth root must be an object")
    allowed = {"hole", "board", "pot", "n_players", "position"}
    if not {"hole", "board", "pot"}.issubset(raw) or not set(raw).issubset(allowed):
        raise ScientificGateError("ground truth has an unsupported schema")
    hole, board, pot = raw.get("hole"), raw.get("board"), raw.get("pot")
    cards = [*hole, *board] if isinstance(hole, list) and isinstance(board, list) else []
    card_re = re.compile(r"[2-9TJQKA][shdc]")
    if (
        not isinstance(hole, list)
        or len(hole) != 2
        or not isinstance(board, list)
        or len(board) not in {0, 3, 4, 5}
        or not all(isinstance(card, str) and card_re.fullmatch(card) for card in cards)
        or len(cards) != len(set(cards))
        or type(pot) is not int
        or not 0 <= pot <= 2_147_483_647
    ):
        raise ScientificGateError("ground truth is semantically invalid")
    n_players = raw.get("n_players")
    if n_players is not None and (type(n_players) is not int or not 2 <= n_players <= 9):
        raise ScientificGateError("ground truth player count is invalid")
    position = raw.get("position")
    if position is not None and (
        not isinstance(position, str) or not 1 <= len(position) <= 16 or not position.isascii()
    ):
        raise ScientificGateError("ground truth position is invalid")
    return raw


def _prediction(raw: object) -> dict[str, Any]:
    value = _exact_fields(
        raw,
        {"hole", "board", "pot", "n_players", "position"},
        "prediction",
    )
    # Reuse the truth semantic validator without trusting a path or normalizing values.
    hole, board, pot = value["hole"], value["board"], value["pot"]
    card_re = re.compile(r"[2-9TJQKA][shdc]")
    cards = [*hole, *board] if isinstance(hole, list) and isinstance(board, list) else []
    if (
        not isinstance(hole, list)
        or len(hole) not in {0, 2}
        or not isinstance(board, list)
        or len(board) not in {0, 3, 4, 5}
        or not all(isinstance(card, str) and card_re.fullmatch(card) for card in cards)
        or len(cards) != len(set(cards))
        or (pot is not None and (type(pot) is not int or not 0 <= pot <= 2_147_483_647))
    ):
        raise ScientificGateError("prediction is semantically invalid")
    n_players, position = value["n_players"], value["position"]
    if n_players is not None and (type(n_players) is not int or not 0 <= n_players <= 9):
        raise ScientificGateError("prediction player count is invalid")
    if position is not None and (
        not isinstance(position, str) or not 1 <= len(position) <= 16 or not position.isascii()
    ):
        raise ScientificGateError("prediction position is invalid")
    return value


def _exact_state(prediction: dict[str, Any], truth: dict[str, Any]) -> bool:
    fields = [
        len(prediction["hole"]) == 2 and set(prediction["hole"]) == set(truth["hole"]),
        prediction["board"] == truth["board"],
        prediction["pot"] == truth["pot"],
    ]
    for optional in ("n_players", "position"):
        if optional in truth:
            fields.append(prediction[optional] == truth[optional])
    return all(fields)


def _candidate_runner(
    artifact_path: Path,
    candidate_manifest_path: Path,
    *,
    _clock: Callable[[], float] | None = None,
) -> Any:
    """Construct the only promotion-grade runner: the actual pinned F2 pipeline."""

    if _clock is None:
        from time import perf_counter

        _clock = perf_counter

    from poker_arena.model_artifacts import verify_evaluation_candidate
    from poker_arena.vision.onnx_recognize import OnnxRecognizer
    from poker_arena.vision.sanity import check_state

    artifact = verify_evaluation_candidate(
        artifact_path, "vision", manifest_path=candidate_manifest_path
    )
    recognizer = OnnxRecognizer(
        artifact.path,
        manifest_path=artifact.manifest_path,
        artifact=artifact,
        allow_evaluation_candidate=True,
    )

    def run(payload: bytes) -> tuple[dict[str, Any], float, bool, float]:
        started = _clock()
        try:
            with Image.open(io.BytesIO(payload)) as image:
                if (
                    image.width < 1
                    or image.height < 1
                    or image.width > MAX_IMAGE_DIMENSION
                    or image.height > MAX_IMAGE_DIMENSION
                    or image.width * image.height > MAX_IMAGE_PIXELS
                ):
                    raise ScientificGateError(
                        "image dimensions exceed the evaluation profile"
                    )
                image.load()
                state = recognizer.recognize(image.convert("RGB"), True, False)
        except (OSError, UnidentifiedImageError) as exc:
            raise ScientificGateError("trusted runner could not decode an image") from exc
        sanity = check_state(state, abstain_below=0.85)
        elapsed_ms = (_clock() - started) * 1_000
        critical = [float(state.confidence)]
        critical.extend(float(value) for value in state.card_confidences)
        if state.pot_confidence is not None:
            critical.append(float(state.pot_confidence))
        confidence = min((value for value in critical if math.isfinite(value)), default=0.0)
        confidence = min(1.0, max(0.0, confidence))
        prediction = {
            "hole": list(state.hole),
            "board": list(state.board),
            "pot": state.pot,
            "n_players": state.n_players,
            "position": state.position,
        }
        return prediction, confidence, sanity.ok, elapsed_ms

    return run


def _wilson(successes: int, total: int, *, upper: bool) -> float:
    if total <= 0:
        return 1.0 if upper else 0.0
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total**2))
    return min(1.0, center + margin / denominator) if upper else max(
        0.0, center - margin / denominator
    )


def _percentile95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def _ece(confidences: list[float], outcomes: list[bool]) -> float:
    total = len(outcomes)
    result = 0.0
    for index in range(10):
        low, high = index / 10, (index + 1) / 10
        members = [
            position
            for position, confidence in enumerate(confidences)
            if low <= confidence <= high and (index == 9 or confidence < high)
        ]
        if members:
            accuracy = fmean(float(outcomes[position]) for position in members)
            confidence = fmean(confidences[position] for position in members)
            result += len(members) / total * abs(accuracy - confidence)
    return result


def _image_signature(payload: bytes) -> tuple[int, str]:
    try:
        with Image.open(io.BytesIO(payload)) as image:
            if (
                image.width < 1
                or image.height < 1
                or image.width > MAX_IMAGE_DIMENSION
                or image.height > MAX_IMAGE_DIMENSION
                or image.width * image.height > MAX_IMAGE_PIXELS
            ):
                raise ScientificGateError("image dimensions exceed the evaluation profile")
            image.load()
            resolution = f"{image.width}x{image.height}"
            raw_pixels = image.convert("L").resize((9, 8)).get_flattened_data()
            if not all(isinstance(value, (int, float)) for value in raw_pixels):
                raise ScientificGateError("image grayscale conversion is invalid")
            pixels = [int(value) for value in raw_pixels if isinstance(value, (int, float))]
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise ScientificGateError("an image sample could not be decoded") from exc
    result = 0
    for row in range(8):
        for column in range(8):
            result = (result << 1) | int(
                pixels[row * 9 + column] > pixels[row * 9 + column + 1]
            )
    return result, resolution


def _safe_group_ref(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _near_duplicate_status(signatures: list[tuple[int, str]]) -> str | None:
    """Bounded five-band search: <=4 differing bits share at least one band."""

    indexes: list[dict[int, list[tuple[int, str]]]] = [dict() for _ in range(5)]
    offsets = ((0, 13), (13, 13), (26, 13), (39, 13), (52, 12))
    comparisons = 0
    for signature, split in signatures:
        candidates: set[tuple[int, str]] = set()
        for index, (offset, width) in enumerate(offsets):
            band = (signature >> offset) & ((1 << width) - 1)
            candidates.update(indexes[index].get(band, ()))
        foreign = [candidate for candidate in candidates if candidate[1] != split]
        comparisons += len(foreign)
        if len(foreign) > MAX_NEAR_DUPLICATE_CANDIDATES or comparisons > (
            MAX_NEAR_DUPLICATE_CANDIDATES * max(1, len(signatures))
        ):
            return "ambiguous"
        if any((signature ^ other).bit_count() <= NEAR_DUPLICATE_HAMMING for other, _ in foreign):
            return "leakage"
        for index, (offset, width) in enumerate(offsets):
            band = (signature >> offset) & ((1 << width) - 1)
            bucket = indexes[index].setdefault(band, [])
            if len(bucket) < MAX_NEAR_DUPLICATE_CANDIDATES + 1:
                bucket.append((signature, split))
            else:
                return "ambiguous"
    return None


def _build_metrics(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    outcomes = [bool(row["exact"]) for row in rows]
    confidences = [float(row["confidence"]) for row in rows]
    accepted = [row for row in rows if row["accepted"]]
    false_accepts = sum(not row["exact"] for row in accepted)
    exact = sum(outcomes)
    metrics: dict[str, Any] = {
        "exact_state": exact / len(rows),
        "exact_state_wilson95_lower": _wilson(exact, len(rows), upper=False),
        "coverage": len(accepted) / len(rows),
        "false_accept_rate": false_accepts / len(accepted) if accepted else 1.0,
        "false_accept_wilson95_upper": _wilson(false_accepts, len(accepted), upper=True),
        "ece_10_bin": _ece(confidences, outcomes),
        "brier": fmean((confidence - float(outcome)) ** 2 for confidence, outcome in zip(confidences, outcomes, strict=True)),
        "latency_p95_ms": _percentile95([float(row["latency_ms"]) for row in rows]),
    }
    subgroups: list[dict[str, Any]] = []
    for field in ("source", "client", "theme", "deck", "resolution"):
        values = sorted({str(row[field]) for row in rows})
        for value in values:
            members = [row for row in rows if row[field] == value]
            successes = sum(bool(row["exact"]) for row in members)
            subgroups.append(
                {
                    "field": field,
                    "value_ref": _safe_group_ref(value),
                    "count": len(members),
                    "exact_state": successes / len(members),
                    "exact_state_wilson95_lower": _wilson(
                        successes, len(members), upper=False
                    ),
                }
            )
    return metrics, subgroups


def evaluate_external_holdout(
    artifact_path: str | Path,
    candidate_manifest_path: str | Path,
    dataset_manifest_path: str | Path,
    dataset_root: str | Path,
    observations_path: str | Path,
) -> dict[str, Any]:
    """Evaluate immutable evidence and return a sanitized promotion receipt."""

    artifact = Path(artifact_path)
    candidate_manifest = Path(candidate_manifest_path)
    manifest_path = Path(dataset_manifest_path)
    root = Path(dataset_root)
    observations_file = Path(observations_path)
    artifact_sha256 = _sha256_file(artifact)
    manifest_report = validate_manifest(
        manifest_path,
        dataset_root=root,
        requested_use="model-evaluation",
    )
    if not manifest_report.valid or manifest_report.manifest_receipt is None:
        raise ScientificGateError("dataset manifest failed its mandatory governance gate")
    manifest_sha256 = manifest_report.manifest_receipt.sha256
    manifest = _safe_manifest_snapshot(manifest_path, manifest_sha256)
    observations, observation_payload = _load_json(observations_file, limit=MAX_JSON_BYTES)
    observations_sha256 = hashlib.sha256(observation_payload).hexdigest()
    top = _exact_fields(
        observations,
        {
            "schema_version",
            "profile_revision",
            "artifact_sha256",
            "pipeline",
            "annotation_protocol",
            "records",
        },
        "observations",
    )
    if top["schema_version"] != SCHEMA_VERSION or top["profile_revision"] != PROFILE_REVISION:
        raise ScientificGateError("observations use an unsupported profile")
    if top["artifact_sha256"] != artifact_sha256:
        raise ScientificGateError("observations are not bound to the evaluated artifact")
    pipeline_binding = current_pipeline_binding()
    if top["pipeline"] != pipeline_binding:
        raise ScientificGateError("evaluation plan is bound to a stale or foreign runtime pipeline")
    records = top["records"]
    if not isinstance(records, list) or not 1 <= len(records) <= MAX_RECORDS:
        raise ScientificGateError("observations must contain a bounded non-empty record array")

    samples = manifest.get("samples")
    if not isinstance(samples, list):
        raise ScientificGateError("validated manifest lost its sample inventory")
    by_id: dict[str, dict[str, Any]] = {}
    for sample in samples:
        if not isinstance(sample, dict) or not isinstance(sample.get("id"), str):
            raise ScientificGateError("validated manifest has an invalid sample inventory")
        by_id[sample["id"]] = sample
    def sample_snapshot(sample: dict[str, Any]) -> bytes:
        expected = sample.get("sha256")
        if not isinstance(expected, str):  # pragma: no cover - manifest gate owns it
            raise ScientificGateError("sample digest is invalid")
        return _sample_snapshot(
            _safe_sample_path(root, sample.get("path")),
            expected_sha256=expected,
            limit=MAX_SAMPLE_SNAPSHOT_BYTES,
        )
    protocol = _exact_fields(
        top["annotation_protocol"],
        {
            "id",
            "version",
            "preregistered_at",
            "evidence_sample_id",
            "evidence_sha256",
            "min_annotators",
            "adjudication",
            "blind_to_model",
        },
        "annotation protocol",
    )
    if (
        not isinstance(protocol["id"], str)
        or _ID_RE.fullmatch(protocol["id"]) is None
        or not isinstance(protocol["version"], str)
        or _ID_RE.fullmatch(protocol["version"]) is None
        or type(protocol["min_annotators"]) is not int
        or protocol["min_annotators"] < 2
        or protocol["adjudication"] != "required-for-disagreement"
        or protocol["blind_to_model"] is not True
        or not isinstance(protocol["evidence_sha256"], str)
        or _SHA256_RE.fullmatch(protocol["evidence_sha256"]) is None
    ):
        raise ScientificGateError("annotation protocol is not preregistered and independent")
    try:
        preregistered_at = datetime.strptime(
            protocol["preregistered_at"], "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=UTC)
    except (TypeError, ValueError) as exc:
        raise ScientificGateError("annotation protocol timestamp is invalid") from exc
    evidence_id = protocol["evidence_sample_id"]
    evidence_sample = by_id.get(evidence_id) if isinstance(evidence_id, str) else None
    if (
        evidence_sample is None
        or evidence_sample.get("sha256") != protocol["evidence_sha256"]
        or not isinstance(evidence_sample.get("path"), str)
        or Path(evidence_sample["path"]).suffix.lower() not in {".json", ".pdf", ".md"}
    ):
        raise ScientificGateError("annotation protocol evidence is absent from the manifest")
    sample_snapshot(evidence_sample)
    split_names = {sample.get("split") for sample in samples}
    failures: list[dict[str, str]] = []
    if EXTERNAL_SPLIT not in split_names or not ({"train", "validation"} & split_names):
        failures.append(
            {"code": "external_split_missing", "message": "An external split and a development split are required."}
        )

    rows: list[dict[str, Any]] = []
    signature_cache: dict[str, tuple[int, str]] = {}
    trusted_runner = _candidate_runner(artifact, candidate_manifest)

    def sample_signature(sample: dict[str, Any]) -> tuple[int, str]:
        sample_id = sample["id"]
        cached = signature_cache.get(sample_id)
        if cached is None:
            cached = _image_signature(sample_snapshot(sample))
            signature_cache[sample_id] = cached
        return cached

    seen_records: set[str] = set()
    seen_images: set[str] = set()
    seen_truth: set[str] = set()
    paired_fields = {
        "source",
        "source_version",
        "session",
        "client",
        "theme",
        "deck",
        "hashed_player_id",
        "event_time",
        "split_group",
        "split",
        "license",
    }
    for raw in records:
        record = _exact_fields(
            raw,
            {
                "id",
                "image_sample_id",
                "truth_sample_id",
                "annotation",
            },
            "observation record",
        )
        record_id = record["id"]
        if not isinstance(record_id, str) or _ID_RE.fullmatch(record_id) is None:
            raise ScientificGateError("observation id is invalid")
        if record_id in seen_records:
            raise ScientificGateError("observation ids must be unique")
        seen_records.add(record_id)
        image_id, truth_id = record["image_sample_id"], record["truth_sample_id"]
        if not isinstance(image_id, str) or not isinstance(truth_id, str):
            raise ScientificGateError("observation sample references are invalid")
        if image_id in seen_images or truth_id in seen_truth:
            raise ScientificGateError("holdout samples may be evaluated only once")
        if image_id == evidence_id or truth_id == evidence_id:
            raise ScientificGateError("annotation protocol evidence cannot be an evaluation sample")
        seen_images.add(image_id)
        seen_truth.add(truth_id)
        image_sample, truth_sample = by_id.get(image_id), by_id.get(truth_id)
        if image_sample is None or truth_sample is None:
            raise ScientificGateError("observation references an undeclared sample")
        if image_sample.get("split") != EXTERNAL_SPLIT or truth_sample.get("split") != EXTERNAL_SPLIT:
            raise ScientificGateError("every evaluated sample must belong to external-test")
        if any(image_sample.get(field) != truth_sample.get(field) for field in paired_fields):
            raise ScientificGateError("image and truth sidecar do not share one provenance group")
        try:
            event_time = datetime.strptime(
                image_sample["event_time"], "%Y-%m-%dT%H:%M:%SZ"
            ).replace(tzinfo=UTC)
        except (KeyError, TypeError, ValueError) as exc:  # pragma: no cover - manifest gate owns it
            raise ScientificGateError("sample event time is invalid") from exc
        if preregistered_at >= event_time:
            raise ScientificGateError("annotation protocol was not registered before collection")
        annotation = _exact_fields(
            record["annotation"],
            {"annotator_count", "agreement", "adjudicated"},
            "record annotation evidence",
        )
        if (
            type(annotation["annotator_count"]) is not int
            or annotation["annotator_count"] < protocol["min_annotators"]
            or type(annotation["agreement"]) is not bool
            or type(annotation["adjudicated"]) is not bool
            or (not annotation["agreement"] and not annotation["adjudicated"])
        ):
            raise ScientificGateError("record lacks independent annotation/adjudication evidence")
        image_relative = image_sample.get("path")
        truth_relative = truth_sample.get("path")
        if (
            not isinstance(image_relative, str)
            or not isinstance(truth_relative, str)
            or Path(image_relative).suffix.lower() not in _IMAGE_SUFFIXES
            or Path(truth_relative).suffix.lower() != ".json"
        ):
            raise ScientificGateError("observation sample roles are invalid")
        image_snapshot = sample_snapshot(image_sample)
        signature_cache[image_id] = _image_signature(image_snapshot)
        truth = _truth(sample_snapshot(truth_sample))
        raw_prediction, confidence, accepted, latency = trusted_runner(image_snapshot)
        del image_snapshot
        prediction = _prediction(raw_prediction)
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(float(confidence))
            or not 0 <= float(confidence) <= 1
        ):
            raise ScientificGateError("confidence must be finite and bounded")
        if type(accepted) is not bool:
            raise ScientificGateError("accepted must be boolean")
        if (
            isinstance(latency, bool)
            or not isinstance(latency, (int, float))
            or not math.isfinite(float(latency))
            or not 0 <= float(latency) <= 3_600_000
        ):
            raise ScientificGateError("latency must be finite and bounded")
        rows.append(
            {
                "exact": _exact_state(prediction, truth),
                "confidence": float(confidence),
                "accepted": accepted,
                "latency_ms": float(latency),
                "resolution": sample_signature(image_sample)[1],
                **{
                    field: image_sample[field]
                    for field in ("source", "client", "theme", "deck", "session")
                },
            }
        )

    external_images = {
        sample["id"]
        for sample in samples
        if sample.get("split") == EXTERNAL_SPLIT
        and isinstance(sample.get("path"), str)
        and Path(sample["path"]).suffix.lower() in _IMAGE_SUFFIXES
    }
    if seen_images != external_images:
        failures.append(
            {"code": "holdout_not_exhaustive", "message": "Every external-test image must be evaluated exactly once."}
        )

    image_samples = [
        sample
        for sample in samples
        if isinstance(sample.get("path"), str)
        and Path(sample["path"]).suffix.lower() in _IMAGE_SUFFIXES
    ]
    hashes = [(sample_signature(sample)[0], sample["split"]) for sample in image_samples]
    near_duplicate_status = _near_duplicate_status(hashes)
    if near_duplicate_status == "leakage":
        failures.append(
            {
                "code": "near_duplicate_leakage",
                "message": "A perceptual near-duplicate crosses dataset splits.",
            }
        )
    elif near_duplicate_status == "ambiguous":
        failures.append(
            {
                "code": "near_duplicate_search_ambiguous",
                "message": "Bounded near-duplicate analysis could not prove split independence.",
            }
        )

    metrics, subgroups = _build_metrics(rows)
    if len(rows) < MIN_TOTAL:
        failures.append({"code": "insufficient_holdout", "message": "External holdout is below the minimum sample size."})
    diversity = {
        "clients": len({row["client"] for row in rows}),
        "themes": len({row["theme"] for row in rows}),
        "decks": len({row["deck"] for row in rows}),
        "sources": len({row["source"] for row in rows}),
        "sessions": len({row["session"] for row in rows}),
        "resolutions": len({row["resolution"] for row in rows}),
    }
    if (
        diversity["sources"] < MIN_SOURCES
        or diversity["clients"] < MIN_CLIENTS
        or diversity["themes"] < MIN_THEMES
        or diversity["decks"] < MIN_DECKS
        or diversity["sessions"] < MIN_SESSIONS
        or diversity["resolutions"] < MIN_RESOLUTIONS
    ):
        failures.append(
            {
                "code": "insufficient_diversity",
                "message": "External holdout lacks required independent source, client, theme, deck, session, or resolution diversity.",
            }
        )
    if sum(row["accepted"] for row in rows) < MIN_ACCEPTED:
        failures.append(
            {
                "code": "insufficient_accepted_predictions",
                "message": "Too few accepted predictions exist for conservative false-accept calibration.",
            }
        )
    if any(group["count"] < MIN_SUBGROUP for group in subgroups):
        failures.append({"code": "subgroup_too_small", "message": "At least one declared subgroup is below the minimum sample size."})
    if any(
        group["exact_state_wilson95_lower"] < MIN_SUBGROUP_EXACT_LCB
        for group in subgroups
    ):
        failures.append(
            {
                "code": "subgroup_accuracy_below_floor",
                "message": "At least one declared subgroup is below the exact-state confidence floor.",
            }
        )
    if metrics["exact_state_wilson95_lower"] < MIN_EXACT_LCB:
        failures.append({"code": "accuracy_below_floor", "message": "Exact-state confidence bound is below policy."})
    if metrics["false_accept_wilson95_upper"] > MAX_FALSE_ACCEPT_UCB:
        failures.append({"code": "false_accept_above_ceiling", "message": "False-accept confidence bound exceeds policy."})
    if metrics["ece_10_bin"] > MAX_ECE or metrics["brier"] > MAX_BRIER:
        failures.append({"code": "calibration_failed", "message": "Calibration metrics exceed policy."})
    if metrics["latency_p95_ms"] > MAX_LATENCY_P95_MS:
        failures.append({"code": "latency_failed", "message": "P95 latency exceeds policy."})

    return {
        "schema_version": SCHEMA_VERSION,
        "profile_revision": PROFILE_REVISION,
        "decision": "pass" if not failures else "fail",
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "artifact_sha256": artifact_sha256,
        "dataset_manifest_sha256": manifest_sha256,
        "observations_sha256": observations_sha256,
        "pipeline": pipeline_binding,
        "execution_environment": execution_environment(),
        "policy": dict(_POLICY),
        "counts": {"total": len(rows), "accepted": sum(row["accepted"] for row in rows), **diversity},
        "metrics": metrics,
        "subgroups": subgroups,
        "failures": failures,
    }


def write_receipt(path: str | Path, receipt: dict[str, Any]) -> str:
    """Write canonical receipt bytes once; existing evidence is never overwritten."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()
    if len(payload) > MAX_RECEIPT_BYTES:
        raise ScientificGateError("promotion receipt exceeds the bounded profile")
    try:
        with target.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise ScientificGateError("promotion receipt already exists") from exc
    return hashlib.sha256(payload).hexdigest()


def verify_promotion_receipt(
    path: str | Path,
    *,
    expected_sha256: str,
    artifact_sha256: str,
) -> VerifiedPromotionEvidence:
    """Validate the hash-pinned scientific receipt used by the runtime gate."""

    if _SHA256_RE.fullmatch(expected_sha256) is None or _SHA256_RE.fullmatch(artifact_sha256) is None:
        raise PromotionEvidenceError("receipt_invalid", "digest fields are invalid")
    try:
        data, payload = _load_json(Path(path), limit=MAX_RECEIPT_BYTES)
    except ScientificGateError as exc:
        raise PromotionEvidenceError("receipt_unreadable", "receipt could not be read safely") from exc
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected_sha256:
        raise PromotionEvidenceError("receipt_sha256_mismatch", "receipt digest does not match")
    required = {
        "schema_version", "profile_revision", "decision", "generated_at",
        "artifact_sha256", "dataset_manifest_sha256", "observations_sha256",
        "pipeline", "execution_environment", "policy", "counts", "metrics",
        "subgroups", "failures",
    }
    if set(data) != required or data.get("schema_version") != SCHEMA_VERSION or data.get("profile_revision") != PROFILE_REVISION:
        raise PromotionEvidenceError("receipt_invalid", "receipt schema or profile is unsupported")
    if data.get("decision") != "pass" or data.get("failures") != []:
        raise PromotionEvidenceError("receipt_failed", "scientific decision is not pass")
    if data.get("artifact_sha256") != artifact_sha256:
        raise PromotionEvidenceError("artifact_mismatch", "receipt belongs to another artifact")
    try:
        current_pipeline = current_pipeline_binding()
    except ScientificGateError as exc:
        raise PromotionEvidenceError(
            "pipeline_unverifiable", "current runtime pipeline could not be verified"
        ) from exc
    if data.get("pipeline") != current_pipeline:
        raise PromotionEvidenceError(
            "pipeline_mismatch", "receipt belongs to a stale or foreign runtime pipeline"
        )
    environment = data.get("execution_environment")
    environment_keys = set(execution_environment())
    if not isinstance(environment, dict) or set(environment) != environment_keys:
        raise PromotionEvidenceError("receipt_invalid", "execution environment is incomplete")
    if any(
        isinstance(value, (dict, list)) or value is None
        for value in environment.values()
    ):
        raise PromotionEvidenceError("receipt_invalid", "execution environment is invalid")
    if environment.get("execution_provider") != "CPUExecutionProvider":
        raise PromotionEvidenceError("receipt_invalid", "execution provider is unsupported")
    if data.get("policy") != _POLICY:
        raise PromotionEvidenceError("policy_mismatch", "receipt policy differs from the mandatory profile")
    for field in ("dataset_manifest_sha256", "observations_sha256"):
        if not isinstance(data.get(field), str) or _SHA256_RE.fullmatch(data[field]) is None:
            raise PromotionEvidenceError("receipt_invalid", "receipt lineage digest is invalid")
    counts, metrics, subgroups = data.get("counts"), data.get("metrics"), data.get("subgroups")
    if not isinstance(counts, dict) or counts.get("total", 0) < MIN_TOTAL:
        raise PromotionEvidenceError("insufficient_holdout", "receipt sample count is below policy")
    count_floors = {
        "accepted": MIN_ACCEPTED,
        "sources": MIN_SOURCES,
        "clients": MIN_CLIENTS,
        "themes": MIN_THEMES,
        "decks": MIN_DECKS,
        "sessions": MIN_SESSIONS,
        "resolutions": MIN_RESOLUTIONS,
    }
    if any(
        type(counts.get(name)) is not int or counts[name] < floor
        for name, floor in count_floors.items()
    ):
        raise PromotionEvidenceError(
            "insufficient_diversity", "receipt diversity or acceptance count is below policy"
        )
    if not isinstance(metrics, dict) or not isinstance(subgroups, list) or not subgroups:
        raise PromotionEvidenceError("receipt_invalid", "receipt metrics are incomplete")
    numeric_checks = (
        ("exact_state_wilson95_lower", MIN_EXACT_LCB, True),
        ("false_accept_wilson95_upper", MAX_FALSE_ACCEPT_UCB, False),
        ("ece_10_bin", MAX_ECE, False),
        ("brier", MAX_BRIER, False),
        ("latency_p95_ms", MAX_LATENCY_P95_MS, False),
    )
    for name, threshold, minimum in numeric_checks:
        value = metrics.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise PromotionEvidenceError("receipt_invalid", "receipt metric is invalid")
        if (minimum and value < threshold) or (not minimum and value > threshold):
            raise PromotionEvidenceError("metric_failed", "receipt metric violates policy")
    for group in subgroups:
        if not isinstance(group, dict) or group.get("count", 0) < MIN_SUBGROUP:
            raise PromotionEvidenceError("subgroup_failed", "receipt subgroup evidence is insufficient")
        lower = group.get("exact_state_wilson95_lower")
        if (
            isinstance(lower, bool)
            or not isinstance(lower, (int, float))
            or not math.isfinite(float(lower))
            or not 0 <= lower <= 1
            or lower < MIN_SUBGROUP_EXACT_LCB
        ):
            raise PromotionEvidenceError("subgroup_failed", "receipt subgroup accuracy is insufficient")
    generated_at = data.get("generated_at")
    try:
        if not isinstance(generated_at, str) or datetime.strptime(generated_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC) > datetime.now(UTC):
            raise ValueError
    except ValueError as exc:
        raise PromotionEvidenceError("receipt_invalid", "receipt timestamp is invalid") from exc
    return VerifiedPromotionEvidence(
        path=Path(path).resolve(),
        sha256=actual,
        artifact_sha256=artifact_sha256,
        dataset_manifest_sha256=data["dataset_manifest_sha256"],
        observations_sha256=data["observations_sha256"],
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fail-closed external vision holdout gate")
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--candidate-manifest", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--observations", required=True)
    parser.add_argument("--receipt", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        receipt = evaluate_external_holdout(
            arguments.artifact,
            arguments.candidate_manifest,
            arguments.manifest,
            arguments.root,
            arguments.observations,
        )
        digest = write_receipt(arguments.receipt, receipt)
    except ScientificGateError as exc:
        print(json.dumps({"decision": "error", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"decision": receipt["decision"], "receipt_sha256": digest}, sort_keys=True))
    return 0 if receipt["decision"] == "pass" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
