"""Export the immutable synthetic table used in the offline defense demo."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Any

from poker_arena.vision.synth import CANONICAL, render_table

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = PROJECT_ROOT / "docs" / "demo"
SEED = 2


def fixture_payload() -> tuple[bytes, dict[str, Any]]:
    image, truth = render_table(
        seed=SEED,
        style=CANONICAL,
        n_board=5,
        noise=0.0,
        with_seats=True,
    )
    output = io.BytesIO()
    image.save(output, format="PNG")
    image_bytes = output.getvalue()
    public_truth = {
        field: truth[field] for field in ("hole", "board", "pot", "n_players", "position")
    }
    receipt = {
        "schema_version": 1,
        "fixture": f"synthetic-canonical-seed-{SEED}",
        "scope": "local-defense-pipeline-demonstration-only",
        "external_validation": False,
        "png_sha256": hashlib.sha256(image_bytes).hexdigest(),
        "truth": public_truth,
    }
    return image_bytes, receipt


def write_fixture(output_directory: Path = DEFAULT_OUTPUT) -> tuple[Path, Path]:
    output_directory.mkdir(parents=True, exist_ok=True)
    image_path = output_directory / "BANCA_TABLE_FIXTURE_SEED_2.png"
    receipt_path = output_directory / "BANCA_TABLE_FIXTURE_SEED_2.json"
    if image_path.exists() or receipt_path.exists():
        raise FileExistsError("fixture da banca ja existe; sobrescrita recusada")
    image_bytes, receipt = fixture_payload()
    receipt_bytes = (
        json.dumps(receipt, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode()
    with image_path.open("xb") as stream:
        stream.write(image_bytes)
    try:
        with receipt_path.open("xb") as stream:
            stream.write(receipt_bytes)
    except OSError:
        image_path.unlink(missing_ok=True)
        raise
    return image_path, receipt_path


def main() -> int:
    image_path, receipt_path = write_fixture()
    print(image_path.relative_to(PROJECT_ROOT).as_posix())
    print(receipt_path.relative_to(PROJECT_ROOT).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
