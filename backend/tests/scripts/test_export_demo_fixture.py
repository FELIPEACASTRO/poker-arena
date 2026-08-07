from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from scripts import export_demo_fixture


def test_fixture_payload_is_deterministic_and_self_describing() -> None:
    first_image, first_receipt = export_demo_fixture.fixture_payload()
    second_image, second_receipt = export_demo_fixture.fixture_payload()

    assert first_image == second_image
    assert first_receipt == second_receipt
    assert first_receipt["schema_version"] == 1
    assert first_receipt["fixture"] == "synthetic-canonical-seed-2"
    assert first_receipt["scope"] == "local-defense-pipeline-demonstration-only"
    assert first_receipt["external_validation"] is False
    assert first_receipt["png_sha256"] == hashlib.sha256(first_image).hexdigest()
    assert set(first_receipt["truth"]) == {
        "hole",
        "board",
        "pot",
        "n_players",
        "position",
    }


def test_write_fixture_creates_valid_png_and_receipt(tmp_path: Path) -> None:
    image_path, receipt_path = export_demo_fixture.write_fixture(tmp_path)

    with Image.open(image_path) as image:
        image.verify()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["png_sha256"] == hashlib.sha256(image_path.read_bytes()).hexdigest()


def test_write_fixture_refuses_overwrite_without_modifying_files(tmp_path: Path) -> None:
    image_path, receipt_path = export_demo_fixture.write_fixture(tmp_path)
    original_image = image_path.read_bytes()
    original_receipt = receipt_path.read_bytes()

    with pytest.raises(FileExistsError, match="sobrescrita recusada"):
        export_demo_fixture.write_fixture(tmp_path)

    assert image_path.read_bytes() == original_image
    assert receipt_path.read_bytes() == original_receipt
