from __future__ import annotations

import pytest

from scripts import demo_preflight


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
