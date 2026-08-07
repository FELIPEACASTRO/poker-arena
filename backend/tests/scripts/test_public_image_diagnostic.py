from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from poker_arena.vision.recognize import RecognizedState
from scripts import public_image_diagnostic as diagnostic


def _manifest(tmp_path: Path, **sample_overrides) -> Path:
    image = tmp_path / "table.png"
    Image.new("RGB", (80, 50), "green").save(image)
    sample = {
        "image": image.name,
        "source_url": "https://commons.wikimedia.org/wiki/File:Example.png",
        "license": {
            "id": "CC-BY-SA-4.0",
            "url": "https://creativecommons.org/licenses/by-sa/4.0/",
        },
        "attribution": "Example Author",
        "rights_confirmed": True,
        "redaction_reviewed": True,
        "redact_boxes": [[0, 0, 10, 10]],
    }
    sample.update(sample_overrides)
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps({"schema_version": 1, "purpose": "diagnostic-only", "samples": [sample]}),
        encoding="utf-8",
    )
    return path


def _state(*, pot: int = 20) -> RecognizedState:
    return RecognizedState(
        hole=["As", "Kd"],
        board=["2h", "6c", "Tc"],
        pot=pot,
        n_cards=5,
        confidence=0.99,
        card_confidences=[0.99] * 5,
        pot_confidence=0.99,
        n_players=6,
        position="BTN",
        pot_source="ocr",
    )


def test_diagnostic_writes_sanitized_report_overlay_and_optional_metrics(tmp_path):
    manifest = _manifest(tmp_path)
    (tmp_path / "table.truth.json").write_text(
        json.dumps(
            {
                "hole": ["Kd", "As"],
                "board": ["2h", "6c", "Tc"],
                "pot": 20,
                "n_players": 6,
                "position": "BTN",
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "out"

    report = diagnostic.run_diagnostic(manifest, output, engines={"stub": lambda _img: _state()})

    assert report["diagnostic_only"] is True
    assert report["scientific_benchmark"] is False
    assert report["promotion_evidence"] is False
    assert report["labelled_sample_count"] == 1
    assert len(report["samples"][0]["truth_sha256"]) == 64
    assert report["descriptive_metrics"]["stub"]["labelled_metrics"]["exact_state"] == {
        "correct": 1,
        "labelled": 1,
        "rate": 1.0,
    }
    sample = report["samples"][0]
    serialized = (output / "diagnostic_report.json").read_text(encoding="utf-8")
    assert str(tmp_path) not in serialized
    assert "commons.wikimedia.org" not in serialized
    assert sample["sample_id"] in serialized
    overlay = Image.open(output / sample["overlay"])
    assert overlay.getpixel((5, 5)) == (0, 0, 0)
    assert not overlay.getexif()


def test_gif_first_frame_and_declared_crop_are_recorded_without_mutating_source(tmp_path):
    first = Image.new("RGB", (80, 50), "green")
    second = Image.new("RGB", (80, 50), "red")
    gif = tmp_path / "table.gif"
    first.save(gif, save_all=True, append_images=[second], duration=100, loop=0)
    original = gif.read_bytes()
    manifest = _manifest(tmp_path, image="table.gif", crop_box=[10, 5, 40, 30])
    seen = []

    report = diagnostic.run_diagnostic(
        manifest,
        tmp_path / "out",
        engines={
            "stub": lambda image: seen.append((image.size, image.getpixel((0, 0)))) or _state()
        },
    )

    sample = report["samples"][0]
    assert seen == [((40, 30), (0, 128, 0))]
    assert sample["source_dimensions"] == [80, 50]
    assert sample["inference_dimensions"] == [40, 30]
    assert sample["frame_index"] == 0
    assert sample["frame_count"] == 2
    assert sample["crop_box"] == [10, 5, 40, 30]
    assert gif.read_bytes() == original


def test_full_and_cropped_variants_receive_distinct_ids(tmp_path):
    full_manifest = _manifest(tmp_path)
    full = diagnostic.run_diagnostic(
        full_manifest, tmp_path / "full", engines={"stub": lambda _image: _state()}
    )
    cropped_data = json.loads(full_manifest.read_text(encoding="utf-8"))
    cropped_data["samples"][0]["crop_box"] = [0, 0, 40, 25]
    cropped_manifest = tmp_path / "cropped.json"
    cropped_manifest.write_text(json.dumps(cropped_data), encoding="utf-8")
    cropped = diagnostic.run_diagnostic(
        cropped_manifest, tmp_path / "cropped", engines={"stub": lambda _image: _state()}
    )

    assert full["samples"][0]["sample_id"] != cropped["samples"][0]["sample_id"]


def test_unlabelled_sample_is_diagnostic_and_has_no_accuracy_metric(tmp_path):
    report = diagnostic.run_diagnostic(
        _manifest(tmp_path), tmp_path / "out", engines={"stub": lambda _img: _state()}
    )

    assert report["labelled_sample_count"] == 0
    assert report["descriptive_metrics"]["stub"]["labelled_metrics"] == {}
    assert "score" not in report["samples"][0]["engines"]["stub"]


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"source_url": "https://google.com/search?q=poker"}, "search index"),
        ({"source_url": "http://example.test/table.png"}, "HTTPS"),
        ({"license": {"id": "unknown", "url": "https://example.test/terms"}}, "allowlist"),
        ({"rights_confirmed": False}, "rights_confirmed"),
        ({"redaction_reviewed": False}, "redaction_reviewed"),
        ({"redact_boxes": [[70, 40, 20, 20]]}, "outside"),
    ],
)
def test_manifest_rejects_unsafe_or_ambiguous_samples(tmp_path, override, message):
    manifest = _manifest(tmp_path, **override)
    with pytest.raises(diagnostic.DiagnosticInputError, match=message):
        diagnostic.run_diagnostic(manifest, tmp_path / "out", engines={"stub": lambda _: _state()})


def test_report_does_not_leak_engine_exception_message(tmp_path):
    def fail(_image):
        raise RuntimeError(f"secret path: {tmp_path}")

    report = diagnostic.run_diagnostic(_manifest(tmp_path), tmp_path / "out", engines={"bad": fail})
    result = report["samples"][0]["engines"]["bad"]

    assert result == {"error": "RuntimeError"}
    assert str(tmp_path) not in json.dumps(report)


def test_output_is_non_overwriting(tmp_path):
    manifest = _manifest(tmp_path)
    output = tmp_path / "out"
    diagnostic.run_diagnostic(manifest, output, engines={"stub": lambda _img: _state()})

    with pytest.raises(diagnostic.DiagnosticInputError, match="already exists"):
        diagnostic.run_diagnostic(manifest, output, engines={"stub": lambda _img: _state()})


def test_image_pixel_limit_is_checked_before_decode(monkeypatch, tmp_path):
    manifest = _manifest(tmp_path)
    monkeypatch.setattr(diagnostic, "MAX_IMAGE_PIXELS", 1)

    with pytest.raises(diagnostic.DiagnosticInputError, match="pixel limit"):
        diagnostic.run_diagnostic(manifest, tmp_path / "out", engines={"stub": lambda _: _state()})
