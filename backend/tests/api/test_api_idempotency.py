from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from poker_arena.api.app import create_app
from poker_arena.api.dependencies import get_repository
from poker_arena.application import InMemorySessionRepository


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("POKER_WARMUP", "0")
    app = create_app()
    repository = InMemorySessionRepository()
    app.dependency_overrides[get_repository] = lambda: repository
    return TestClient(app)


def _body(seed: int = 7) -> dict[str, object]:
    return {
        "bots": [{"name": "B", "level": "heuristic"}],
        "seed": seed,
    }


def _create(client: TestClient) -> dict:
    response = client.post("/tables", json=_body())
    assert response.status_code == 201, response.text
    return response.json()


def test_create_table_idempotency_replays_original_response(client: TestClient):
    headers = {"Idempotency-Key": "create-1"}
    first = client.post("/tables", json=_body(), headers=headers)
    replay = client.post("/tables", json=_body(), headers=headers)

    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json()
    assert first.json()["version"] == 0
    assert first.headers["etag"] == '"0"'
    assert first.headers["x-idempotent-replay"] == "false"
    assert replay.headers["x-idempotent-replay"] == "true"

    conflict = client.post("/tables", json=_body(seed=8), headers=headers)
    assert conflict.status_code == 409


def test_session_command_replay_precedes_stale_version_check(client: TestClient):
    state = _create(client)
    table_id = state["table_id"]
    headers = {"Idempotency-Key": "fold-1", "If-Match": "0"}

    first = client.post(
        f"/tables/{table_id}/actions", json={"type": "fold", "amount": 0}, headers=headers
    )
    replay = client.post(
        f"/tables/{table_id}/actions", json={"type": "fold", "amount": 0}, headers=headers
    )

    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    assert first.json()["version"] == 1
    assert first.headers["x-idempotent-replay"] == "false"
    assert replay.headers["x-idempotent-replay"] == "true"

    reused = client.post(
        f"/tables/{table_id}/actions", json={"type": "call", "amount": 0}, headers=headers
    )
    assert reused.status_code == 409


def test_stale_command_conflicts_and_get_is_version_neutral(client: TestClient):
    state = _create(client)
    table_id = state["table_id"]
    assert state["version"] == 0

    assert client.get(f"/tables/{table_id}").json()["version"] == 0
    acted = client.post(
        f"/tables/{table_id}/actions",
        json={"type": "fold", "amount": 0},
        headers={"Idempotency-Key": "fold-1", "If-Match": '"0"'},
    )
    assert acted.status_code == 200
    assert acted.json()["version"] == 1
    assert acted.headers["etag"] == '"1"'
    assert client.get(f"/tables/{table_id}").json()["version"] == 1

    stale = client.post(
        f"/tables/{table_id}/next-hand",
        headers={"Idempotency-Key": "next-stale", "If-Match": "0"},
    )
    assert stale.status_code == 409


@pytest.mark.parametrize(
    "headers",
    [
        {"Idempotency-Key": ""},
        {"Idempotency-Key": "spaces are invalid"},
        {"Idempotency-Key": "x" * 129},
        {"If-Match": "not-a-version"},
        {"If-Match": "-1"},
    ],
)
def test_malformed_command_headers_fail_closed(client: TestClient, headers: dict[str, str]):
    state = _create(client)
    response = client.post(
        f"/tables/{state['table_id']}/actions",
        json={"type": "fold", "amount": 0},
        headers=headers,
    )
    assert response.status_code == 400


def test_two_commands_from_same_version_cannot_both_commit(client: TestClient):
    state = _create(client)
    table_id = state["table_id"]

    def send(command_id: str):
        return client.post(
            f"/tables/{table_id}/actions",
            json={"type": "fold", "amount": 0},
            headers={"Idempotency-Key": command_id, "If-Match": "0"},
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(send, ["concurrent-a", "concurrent-b"]))

    assert sorted(response.status_code for response in responses) == [200, 409]
    assert client.get(f"/tables/{table_id}").json()["version"] == 1
