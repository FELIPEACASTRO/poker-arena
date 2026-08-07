from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import poker_arena.api.app as api_app
from poker_arena.api.dependencies import get_repository
from poker_arena.application import InMemorySessionRepository


def _client(tmp_path, monkeypatch) -> tuple[TestClient, InMemorySessionRepository]:
    monkeypatch.setenv("POKER_WARMUP", "0")
    monkeypatch.setenv("POKER_LOG_DIR", str(tmp_path))
    app = api_app.create_app()
    repository = InMemorySessionRepository()
    app.dependency_overrides[get_repository] = lambda: repository
    return TestClient(app), repository


def _create(client: TestClient, *, key: str | None = None):
    headers = {"Idempotency-Key": key} if key is not None else None
    return client.post(
        "/tables",
        json={"bots": [{"name": "B", "level": "heuristic"}], "seed": 7},
        headers=headers,
    )


def test_create_idempotency_eviction_rejects_without_duplicate(tmp_path, monkeypatch):
    monkeypatch.setattr(api_app, "MAX_IDEMPOTENCY_KEYS", 2)
    client, repository = _client(tmp_path, monkeypatch)

    first = _create(client, key="original")
    assert first.status_code == 201
    assert _create(client, key="second").status_code == 201
    assert _create(client, key="third").status_code == 201
    table_count = len(repository._store)

    expired = _create(client, key="original")

    assert expired.status_code == 409
    assert "não foi criada novamente" in expired.json()["detail"]
    assert len(repository._store) == table_count


def test_giant_if_match_is_a_bounded_400(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    table_id = _create(client).json()["table_id"]

    response = client.post(
        f"/tables/{table_id}/actions",
        json={"type": "fold"},
        headers={"If-Match": "9" * 5000},
    )

    assert response.status_code == 400


def test_websocket_rejects_deep_json_without_closing_connection(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    table_id = _create(client).json()["table_id"]
    nested = '{"type":' + "[" * 40 + '"fold"' + "]" * 40 + "}"

    with client.websocket_connect(f"/tables/{table_id}/ws") as websocket:
        initial = websocket.receive_json()
        websocket.send_text(nested)
        error = websocket.receive_json()
        assert error["code"] == "validation_error"
        assert "profundidade" in error["error"]

        websocket.send_json(
            {
                "type": "fold",
                "command_id": "after-deep-json",
                "expected_version": initial["version"],
            }
        )
        assert websocket.receive_json()["version"] == initial["version"] + 1


def test_rest_mutation_broadcasts_to_every_websocket_client(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    table_id = _create(client).json()["table_id"]

    with client.websocket_connect(f"/tables/{table_id}/ws") as first:
        initial = first.receive_json()
        with client.websocket_connect(f"/tables/{table_id}/ws") as second:
            assert second.receive_json()["version"] == initial["version"]

            response = client.post(
                f"/tables/{table_id}/actions",
                json={"type": "fold"},
                headers={"If-Match": str(initial["version"])},
            )
            assert response.status_code == 200
            expected = response.json()
            assert first.receive_json() == expected
            assert second.receive_json() == expected


def test_game_routes_apply_bounded_pagination(tmp_path, monkeypatch):
    rows = [{"type": "meta", "id": "api-page", "created": "2026-01-01"}]
    rows.extend(
        {"type": "hand", "hand": hand, "ts": f"2026-01-01T00:00:0{hand}"} for hand in range(1, 5)
    )
    (tmp_path / "api-page.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    client, _ = _client(tmp_path, monkeypatch)

    listing = client.get("/games?offset=0&limit=1")
    replay = client.get("/games/api-page?offset=1&limit=2")

    assert listing.status_code == 200
    assert listing.json()["page"]["limit"] == 1
    assert replay.status_code == 200
    assert [hand["hand"] for hand in replay.json()["hands"]] == [2, 3]
    assert replay.json()["page"]["total"] == 4


@pytest.mark.parametrize("limit", [0, 201])
def test_game_route_rejects_out_of_contract_page_limit(tmp_path, monkeypatch, limit):
    client, _ = _client(tmp_path, monkeypatch)
    assert client.get(f"/games?limit={limit}").status_code == 422
