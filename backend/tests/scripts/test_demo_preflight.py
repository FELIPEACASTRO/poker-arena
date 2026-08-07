from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import demo_preflight, export_demo_fixture


def test_demo_fixture_exercises_exact_recognition_and_fail_closed_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "POKER_API_TOKEN",
        "POKER_VLM_URL",
        "POKER_VLM_API_KEY",
        "POKER_ENABLE_REMOTE_VLM",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("POKER_WARMUP", "0")

    result = demo_preflight._exercise_real_image_route()

    assert result["exact_state"] is True
    assert result["decision_blocked"] is True
    assert result["engine"] == "F1-template"
    assert 0 <= result["warm_latency_ms"] <= 4_000


@pytest.mark.parametrize(
    "name",
    ["POKER_API_TOKEN", "POKER_VLM_URL", "POKER_VLM_API_KEY", "POKER_ENABLE_REMOTE_VLM"],
)
def test_demo_profile_rejects_remote_or_authenticated_configuration(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setenv(name, "1" if name == "POKER_ENABLE_REMOTE_VLM" else "configured")

    with pytest.raises(demo_preflight.DemoPreflightError, match="local"):
        demo_preflight._require_local_offline_profile()


@pytest.mark.parametrize("corruption", ["extra-field", "external-claim", "digest"])
def test_demo_fixture_receipt_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, corruption: str
) -> None:
    image_path, receipt_path = export_demo_fixture.write_fixture(tmp_path)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if corruption == "extra-field":
        receipt["unexpected"] = True
    elif corruption == "external-claim":
        receipt["external_validation"] = True
    else:
        receipt["png_sha256"] = "0" * 64
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    monkeypatch.setattr(demo_preflight, "DEMO_IMAGE", image_path)
    monkeypatch.setattr(demo_preflight, "DEMO_RECEIPT", receipt_path)

    with pytest.raises(demo_preflight.DemoPreflightError):
        demo_preflight._exercise_real_image_route()
