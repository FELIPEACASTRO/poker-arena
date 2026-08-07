"""Run a privacy-conscious diagnostic on explicitly licensed public screenshots.

This command is deliberately local-only: it never downloads an image.  A Google
Images result page is not provenance; the manifest must point to the original
publication/licence page and record a human rights/redaction review.  Results are
descriptive smoke-test observations, never a scientific benchmark or promotion
receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import statistics
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from PIL import Image, ImageDraw, UnidentifiedImageError

from poker_arena.vision import (
    check_state,
    recognize_table,
    recognize_table_onnx,
    vision_model_available,
)
from poker_arena.vision.recognize import RecognizedState
from scripts.real_eval import _validate_truth, score_truth

SCHEMA_VERSION = 1
MAX_SAMPLES = 100
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000
MAX_GIF_FRAMES = 100
SUPPORTED_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif"})
OPEN_LICENSES = frozenset(
    {
        "CC0-1.0",
        "PDM-1.0",
        "CC-BY-3.0",
        "CC-BY-4.0",
        "CC-BY-SA-3.0",
        "CC-BY-SA-4.0",
        "GPL-2.0-only",
        "GPL-2.0-or-later",
        "GPL-3.0-only",
        "GPL-3.0-or-later",
        "MIT",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
    }
)
SEARCH_INDEX_HOSTS = frozenset(
    {
        "baidu.com",
        "bing.com",
        "duckduckgo.com",
        "google.com",
        "googleusercontent.com",
        "images.google.com",
        "search.yahoo.com",
        "yandex.com",
    }
)


class DiagnosticInputError(ValueError):
    """The diagnostic input is unsafe, ambiguous or outside its declared contract."""


def _https_url(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) > 2_048:
        raise DiagnosticInputError(f"{field} must be a bounded HTTPS URL")
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise DiagnosticInputError(f"{field} must be a public HTTPS URL without credentials")
    hostname = (parsed.hostname or "").lower().removeprefix("www.")
    if field == "source_url" and any(
        hostname == blocked or hostname.endswith(f".{blocked}") for blocked in SEARCH_INDEX_HOSTS
    ):
        raise DiagnosticInputError(
            "source_url must be the original publication, not a search index"
        )
    return value


def _bounded_string(value: Any, field: str, maximum: int = 500) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise DiagnosticInputError(f"{field} must be a non-empty string up to {maximum} chars")
    if any(ord(char) < 32 for char in value):
        raise DiagnosticInputError(f"{field} contains a control character")
    return value.strip()


def _inside(root: Path, relative: Any, field: str) -> Path:
    text = _bounded_string(relative, field, 240)
    requested = Path(text)
    if requested.is_absolute() or requested.drive or ".." in requested.parts:
        raise DiagnosticInputError(f"{field} must be a relative path without traversal")
    resolved = (root / requested).resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise DiagnosticInputError(f"{field} resolves outside the manifest directory") from exc
    if (root / requested).is_symlink() or not resolved.is_file():
        raise DiagnosticInputError(f"{field} must be a regular in-tree file")
    return resolved


def _load_fixed_image(path: Path) -> tuple[Image.Image, str, int]:
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise DiagnosticInputError("image extension is not supported")
    try:
        with path.open("rb") as stream:
            payload = stream.read(MAX_IMAGE_BYTES + 1)
    except OSError as exc:
        raise DiagnosticInputError("image cannot be read") from exc
    if len(payload) > MAX_IMAGE_BYTES:
        raise DiagnosticInputError("image exceeds the byte limit")
    digest = hashlib.sha256(payload).hexdigest()
    try:
        with Image.open(io.BytesIO(payload)) as probe:
            width, height = probe.size
            frame_count = int(getattr(probe, "n_frames", 1))
            if frame_count < 1 or frame_count > MAX_GIF_FRAMES:
                raise DiagnosticInputError("image exceeds the frame limit")
            if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                raise DiagnosticInputError("image exceeds the pixel limit")
            probe.verify()
        with Image.open(io.BytesIO(payload)) as decoded:
            decoded.seek(0)
            image = decoded.convert("RGB")
            image.load()
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise DiagnosticInputError("image is invalid or truncated") from exc
    return image, digest, frame_count


def _load_optional_truth(image_path: Path, root: Path) -> tuple[dict[str, Any] | None, str | None]:
    candidates = (
        image_path.with_name(f"{image_path.stem}.truth.json"),
        image_path.with_suffix(".json"),
    )
    truth_path = next((path for path in candidates if path.exists()), None)
    if truth_path is None:
        return None, None
    if truth_path.is_symlink():
        raise DiagnosticInputError("truth sidecar must not be a symlink")
    try:
        resolved = truth_path.resolve(strict=True)
        resolved.relative_to(root)
        with resolved.open("rb") as stream:
            payload = stream.read(65_537)
        if len(payload) > 65_536:
            raise DiagnosticInputError("truth sidecar exceeds 64 KiB")
        raw = json.loads(payload)
        return _validate_truth(raw, Path("<truth-sidecar>")), hashlib.sha256(payload).hexdigest()
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        if isinstance(exc, DiagnosticInputError):
            raise
        raise DiagnosticInputError("truth sidecar is invalid") from exc


def _redaction_boxes(raw: Any, width: int, height: int) -> list[tuple[int, int, int, int]]:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > 100:
        raise DiagnosticInputError("redact_boxes must be a list with at most 100 boxes")
    boxes: list[tuple[int, int, int, int]] = []
    for box in raw:
        if (
            not isinstance(box, list)
            or len(box) != 4
            or any(isinstance(value, bool) or not isinstance(value, int) for value in box)
        ):
            raise DiagnosticInputError("each redaction box must be [x,y,width,height]")
        x, y, box_width, box_height = box
        if (
            x < 0
            or y < 0
            or box_width <= 0
            or box_height <= 0
            or x + box_width > width
            or y + box_height > height
        ):
            raise DiagnosticInputError("redaction box is outside the image")
        boxes.append((x, y, box_width, box_height))
    return boxes


def _crop_box(raw: Any, width: int, height: int) -> tuple[int, int, int, int] | None:
    if raw is None:
        return None
    boxes = _redaction_boxes([raw], width, height)
    return boxes[0]


def _processed_view(
    image: Image.Image,
    redactions: list[tuple[int, int, int, int]],
    crop: tuple[int, int, int, int] | None,
) -> tuple[Image.Image, Image.Image]:
    """Return the inference ROI and a redacted copy of exactly that view."""
    inference = image
    display = Image.new("RGB", image.size, "black")
    display.paste(image)
    draw = ImageDraw.Draw(display)
    for x, y, width, height in redactions:
        draw.rectangle((x, y, x + width - 1, y + height - 1), fill="black")
    if crop is not None:
        x, y, width, height = crop
        bounds = (x, y, x + width, y + height)
        inference = inference.crop(bounds)
        display = display.crop(bounds)
    return inference, display


def load_manifest(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        payload = path.read_bytes()
        raw = json.loads(payload)
    except (OSError, json.JSONDecodeError) as exc:
        raise DiagnosticInputError("manifest is not valid JSON") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA_VERSION:
        raise DiagnosticInputError(f"manifest schema_version must be {SCHEMA_VERSION}")
    if raw.get("purpose") != "diagnostic-only":
        raise DiagnosticInputError("manifest purpose must be diagnostic-only")
    samples = raw.get("samples")
    if not isinstance(samples, list) or not samples or len(samples) > MAX_SAMPLES:
        raise DiagnosticInputError(f"samples must contain between 1 and {MAX_SAMPLES} items")
    return raw, payload


def _validate_sample(raw: Any, root: Path) -> tuple[Path, str, list[Any]]:
    if not isinstance(raw, dict):
        raise DiagnosticInputError("sample must be an object")
    image_path = _inside(root, raw.get("image"), "image")
    _https_url(raw.get("source_url"), "source_url")
    licence = raw.get("license")
    if not isinstance(licence, dict) or licence.get("id") not in OPEN_LICENSES:
        raise DiagnosticInputError("license.id is absent or outside the reviewed open allowlist")
    _https_url(licence.get("url"), "license.url")
    _bounded_string(raw.get("attribution"), "attribution")
    if raw.get("rights_confirmed") is not True:
        raise DiagnosticInputError("rights_confirmed must be true after human review")
    if raw.get("redaction_reviewed") is not True:
        raise DiagnosticInputError("redaction_reviewed must be true after human review")
    return image_path, str(licence["id"]), raw.get("redact_boxes", [])


def _state_payload(state: RecognizedState) -> dict[str, Any]:
    return {
        "hole": state.hole,
        "board": state.board,
        "pot": state.pot,
        "n_players": state.n_players,
        "position": state.position,
        "confidence": state.confidence,
        "accepted": check_state(state, abstain_below=0.85).ok,
    }


def _percentile_95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def _overlay(
    image: Image.Image,
    sample_id: str,
    engines: dict[str, dict[str, Any]],
    truth: dict[str, Any] | None,
) -> Image.Image:
    # The caller supplies a redacted view. A fresh RGB canvas also discards metadata.
    clean = Image.new("RGB", image.size, "black")
    clean.paste(image)
    rows = 2 + len(engines) + int(truth is not None)
    panel_height = 20 * rows
    canvas = Image.new("RGB", (clean.width, clean.height + panel_height), (10, 14, 20))
    canvas.paste(clean, (0, 0))
    panel = ImageDraw.Draw(canvas)
    panel.text((8, clean.height + 5), f"DIAGNOSTIC ONLY | sample={sample_id}", fill="white")
    y = clean.height + 25
    for engine, result in sorted(engines.items()):
        state = result.get("state")
        if state is None:
            text = f"{engine}: ERROR ({result['error']})"
        else:
            text = (
                f"{engine}: hole={state['hole']} board={state['board']} pot={state['pot']} "
                f"players={state['n_players']} pos={state['position']} accepted={state['accepted']}"
            )
        panel.text((8, y), text[:220], fill=(190, 215, 235))
        y += 20
    if truth is not None:
        text = (
            f"truth: hole={truth['hole']} board={truth['board']} pot={truth['pot']} "
            f"players={truth.get('n_players')} pos={truth.get('position')}"
        )
        panel.text((8, y), text[:220], fill=(160, 230, 170))
    return canvas


def _engine_functions() -> dict[str, Callable[[Image.Image], RecognizedState]]:
    engines: dict[str, Callable[[Image.Image], RecognizedState]] = {
        "f1_template": lambda image: recognize_table(
            image, ocr_numbers=True, fail_fast_abstain_below=0.85
        )
    }
    if vision_model_available():
        engines["f2_onnx"] = lambda image: recognize_table_onnx(
            image, ocr_numbers=True, fail_fast_abstain_below=0.85
        )
    return engines


def _aggregate(samples: list[dict[str, Any]]) -> dict[str, Any]:
    by_engine: dict[str, dict[str, Any]] = {}
    engine_names = sorted({engine for sample in samples for engine in sample.get("engines", {})})
    for engine in engine_names:
        results = [sample["engines"][engine] for sample in samples if engine in sample["engines"]]
        successes = [result for result in results if "state" in result]
        latencies = [float(result["latency_ms"]) for result in successes]
        scored = [result["score"] for result in successes if "score" in result]
        fields: dict[str, dict[str, int | float]] = {}
        field_names = sorted({field for score in scored for field in score})
        for field in field_names:
            eligible = [score for score in scored if field in score]
            correct = sum(bool(score[field]) for score in eligible)
            fields[field] = {
                "correct": correct,
                "labelled": len(eligible),
                "rate": correct / len(eligible) if eligible else 0.0,
            }
        by_engine[engine] = {
            "attempted": len(results),
            "succeeded": len(successes),
            "accepted": sum(bool(result["state"]["accepted"]) for result in successes),
            "latency_ms": {
                "median": statistics.median(latencies) if latencies else None,
                "p95_nearest_rank": _percentile_95(latencies),
            },
            "labelled_metrics": fields,
        }
    return by_engine


def run_diagnostic(
    manifest_path: Path,
    output_dir: Path,
    *,
    engines: dict[str, Callable[[Image.Image], RecognizedState]] | None = None,
) -> dict[str, Any]:
    manifest_path = manifest_path.resolve(strict=True)
    manifest, manifest_payload = load_manifest(manifest_path)
    root = manifest_path.parent.resolve(strict=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    if not output_dir.resolve().is_dir():
        raise DiagnosticInputError("output must be a directory")
    report_path = output_dir / "diagnostic_report.json"
    if report_path.exists():
        raise DiagnosticInputError("output report already exists; use a new empty run directory")

    selected_engines = engines if engines is not None else _engine_functions()
    if not selected_engines or any(not name.isidentifier() for name in selected_engines):
        raise DiagnosticInputError("at least one safely named engine is required")

    samples: list[dict[str, Any]] = []
    for raw_sample in manifest["samples"]:
        image_path, license_id, raw_boxes = _validate_sample(raw_sample, root)
        image, image_digest, frame_count = _load_fixed_image(image_path)
        boxes = _redaction_boxes(raw_boxes, image.width, image.height)
        crop = _crop_box(raw_sample.get("crop_box"), image.width, image.height)
        inference_image, display_image = _processed_view(image, boxes, crop)
        variant = json.dumps(
            {"image_sha256": image_digest, "frame_index": 0, "crop_box": crop},
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        sample_id = hashlib.sha256(variant).hexdigest()[:16]
        truth, truth_digest = _load_optional_truth(image_path, root)
        engine_results: dict[str, dict[str, Any]] = {}
        for name, engine in sorted(selected_engines.items()):
            started = time.perf_counter()
            try:
                state = engine(inference_image.copy())
                result: dict[str, Any] = {
                    "state": _state_payload(state),
                    "latency_ms": (time.perf_counter() - started) * 1_000,
                }
                if truth is not None:
                    result["score"] = score_truth(state, truth)
            except Exception as exc:  # noqa: BLE001 - sanitize and continue other engines/samples
                result = {"error": type(exc).__name__}
            engine_results[name] = result
        overlay = _overlay(display_image, sample_id, engine_results, truth)
        overlay.save(output_dir / f"{sample_id}.overlay.png", format="PNG")
        samples.append(
            {
                "sample_id": sample_id,
                "image_sha256": image_digest,
                "source_reference_sha256": hashlib.sha256(
                    str(raw_sample["source_url"]).encode("utf-8")
                ).hexdigest(),
                "license_id": license_id,
                "source_dimensions": [image.width, image.height],
                "inference_dimensions": [inference_image.width, inference_image.height],
                "frame_index": 0,
                "frame_count": frame_count,
                "crop_box": list(crop) if crop is not None else None,
                "truth_available": truth is not None,
                "truth_sha256": truth_digest,
                "redaction_box_count": len(boxes),
                "engines": engine_results,
                "overlay": f"{sample_id}.overlay.png",
            }
        )

    report = {
        "schema_version": SCHEMA_VERSION,
        "diagnostic_only": True,
        "scientific_benchmark": False,
        "promotion_evidence": False,
        "manifest_sha256": hashlib.sha256(manifest_payload).hexdigest(),
        "sample_count": len(samples),
        "labelled_sample_count": sum(sample["truth_available"] for sample in samples),
        "samples": samples,
        "descriptive_metrics": _aggregate(samples),
        "limitations": [
            "Convenience/public images are not a representative or independent holdout.",
            "Unlabelled samples provide no correctness metric.",
            "This report cannot authorize model promotion or a generalization claim.",
        ],
    }
    temporary = report_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(report_path)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    try:
        report = run_diagnostic(args.manifest, args.output)
    except DiagnosticInputError as exc:
        print(f"DIAGNOSTIC INPUT REJECTED: {exc}", file=sys.stderr)
        return 2
    failures = sum(
        "error" in result for sample in report["samples"] for result in sample["engines"].values()
    )
    print(
        "DIAGNOSTIC ONLY: "
        f"samples={report['sample_count']} labelled={report['labelled_sample_count']} "
        f"engine_errors={failures} report={Path(args.output) / 'diagnostic_report.json'}"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
