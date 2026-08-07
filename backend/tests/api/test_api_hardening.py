"""Regression tests for API trust boundaries and fail-closed behaviour."""

from __future__ import annotations

import asyncio
import io
import struct
import zlib

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from starlette.websockets import WebSocketDisconnect

from poker_arena.api.app import _ImageBodyLimitMiddleware, _WebSocketHub, create_app
from poker_arena.api.dependencies import get_repository
from poker_arena.application import InMemorySessionRepository
from poker_arena.vision import RecognizedState

VALID_COPILOT_PAYLOAD: dict[str, object] = {
    "hole": ["As", "Kh"],
    "board": [],
    "pot": 10,
    "to_call": 0,
    "my_stack": 100,
    "effective_stack": 100,
    "num_opponents": 1,
    "in_position": False,
    "position": "SB",
    "hero_current_bet": 0,
    "current_bet": 0,
    "min_raise_increment": 20,
    "table_size": 2,
    "raise_reopened": True,
}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("POKER_WARMUP", "0")
    app = create_app()
    repository = InMemorySessionRepository()
    app.dependency_overrides[get_repository] = lambda: repository
    return TestClient(app)


@pytest.mark.parametrize(
    "payload",
    [
        {"mode": "garbage", "bots": [{"name": "B", "level": "heuristic"}]},
        {"mode": "play", "bots": []},
        {"mode": "watch", "bots": [{"name": "B", "level": "heuristic"}]},
        {
            "mode": "watch",
            "bots": [{"name": f"B{i}", "level": "heuristic"} for i in range(10)],
        },
        {
            "bots": [{"name": "B", "level": "heuristic"}],
            "small_blind": 20,
            "big_blind": 10,
        },
        {
            "bots": [{"name": "B", "level": "heuristic"}],
            "hand_limit": -5,
        },
        {
            "bots": [{"name": "B", "level": "not-a-bot"}],
        },
        {
            "bots": [{"name": "B", "level": "heuristic"}],
            "big_bilnd": 999,
        },
        {
            "human_name": "B",
            "bots": [{"name": "B", "level": "heuristic"}],
        },
        {
            "mode": "watch",
            "bots": [
                {"name": "B", "level": "heuristic"},
                {"name": "b", "level": "random"},
            ],
        },
        {"bots": [{"name": "linha\nnova", "level": "heuristic"}]},
        {
            "bots": [{"name": "B", "level": "heuristic"}],
            "starting_stack": 1_000_000_001,
        },
        {
            "bots": [{"name": "B", "level": "heuristic"}],
            "hand_limit": 1_000_001,
        },
    ],
)
def test_create_table_rejects_semantically_invalid_payloads(
    client: TestClient, payload: dict[str, object]
) -> None:
    response = client.post("/tables", json=payload)
    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    ("overrides", "error_field"),
    [
        ({"hole": ["As"]}, "hole"),
        ({"board": ["2c", "3d"]}, "board"),
        ({"num_opponents": 9}, "num_opponents"),
        ({"position": "MARS"}, "position"),
        ({"unexpected": True}, "unexpected"),
        ({"pot": 1_000_000_001}, "pot"),
        ({"pot": True}, "pot"),
        ({"pot": 10.0}, "pot"),
        ({"pot": "10"}, "pot"),
        ({"my_stack": True}, "my_stack"),
        ({"num_opponents": True}, "num_opponents"),
    ],
)
def test_copilot_schema_rejects_invalid_or_unknown_fields(
    client: TestClient, overrides: dict[str, object], error_field: str
) -> None:
    payload = {**VALID_COPILOT_PAYLOAD, **overrides}
    response = client.post("/copilot", json=payload)
    assert response.status_code == 422, response.text
    assert any(error["loc"][-1] == error_field for error in response.json()["detail"]), (
        response.text
    )


def test_copilot_schema_requires_table_size_for_position_semantics(client: TestClient) -> None:
    response = client.post(
        "/copilot",
        json={
            "hole": ["As", "Kh"],
            "board": [],
            "pot": 30,
            "to_call": 10,
            "my_stack": 100,
            "effective_stack": 100,
            "num_opponents": 1,
            "in_position": False,
            "position": "UTG",
            "hero_current_bet": 10,
            "current_bet": 20,
            "min_raise_increment": 20,
            "raise_reopened": True,
        },
    )

    assert response.status_code == 422


def test_hand_review_rejects_unbounded_input(client: TestClient) -> None:
    response = client.post(
        "/copilot/review-hand",
        json={"phh": "x" * 1_000_001, "player": 1},
    )
    assert response.status_code == 422


def _png_bytes() -> bytes:
    image = Image.new("RGB", (32, 32), "green")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_from_image_is_strict_by_default(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    uncertain = RecognizedState(
        hole=["As", "Kh"],
        board=["2c", "3d", "4h"],
        pot=100,
        n_cards=5,
        confidence=0.50,
        n_players=2,
        position="SB",
        pot_source="ocr",
    )
    monkeypatch.setattr("poker_arena.vision.vision_model_available", lambda: False)
    monkeypatch.setattr("poker_arena.vision.recognize_table", lambda *a, **k: uncertain)
    monkeypatch.setattr("poker_arena.vision.vlm_available", lambda: False)

    response = client.post(
        "/copilot/from-image",
        files={"image": ("table.png", _png_bytes(), "image/png")},
        data={"my_stack": "1000"},
    )

    assert response.status_code == 200
    assert response.json()["sanity"]["ok"] is False
    assert response.json()["decision"] is None


def test_from_image_rejects_attempt_to_disable_strict_mode(client: TestClient) -> None:
    response = client.post(
        "/copilot/from-image",
        files={"image": ("table.png", _png_bytes(), "image/png")},
        data={"strict": "false"},
    )

    assert response.status_code == 422


def test_from_image_never_decides_without_a_detected_pot(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing_pot = RecognizedState(
        hole=["As", "Kh"],
        board=["2c", "3d", "4h"],
        pot=None,
        n_cards=5,
        confidence=0.99,
        n_players=2,
        position="BTN",
        pot_source="ocr",
    )
    monkeypatch.setattr("poker_arena.vision.vision_model_available", lambda: False)
    monkeypatch.setattr("poker_arena.vision.recognize_table", lambda *a, **k: missing_pot)
    monkeypatch.setattr("poker_arena.vision.vlm_available", lambda: False)

    response = client.post(
        "/copilot/from-image",
        files={"image": ("table.png", _png_bytes(), "image/png")},
        data={"my_stack": "1000"},
    )

    assert response.status_code == 200
    assert response.json()["sanity"]["ok"] is False
    assert response.json()["decision"] is None


def test_from_image_rejects_wrong_media_type(client: TestClient) -> None:
    response = client.post(
        "/copilot/from-image",
        files={"image": ("table.txt", b"not an image", "text/plain")},
    )
    assert response.status_code == 415


def test_from_image_rejects_oversized_upload(client: TestClient) -> None:
    response = client.post(
        "/copilot/from-image",
        files={"image": ("huge.png", b"0" * (5 * 1024 * 1024 + 1), "image/png")},
    )
    assert response.status_code == 413


def test_streaming_body_limit_rejects_chunked_upload_before_multipart_parser(monkeypatch) -> None:
    monkeypatch.setenv("POKER_MAX_IMAGE_BYTES", "1")
    entered = False
    messages = iter(
        [
            {"type": "http.request", "body": b"x" * 150_000, "more_body": True},
            {"type": "http.request", "body": b"x" * 150_000, "more_body": False},
        ]
    )
    sent = []

    async def receive():
        return next(messages)

    async def send(message):
        sent.append(message)

    async def inner(scope, receive_inner, send_inner):
        nonlocal entered
        entered = True
        while True:
            message = await receive_inner()
            if not message.get("more_body", False):
                break
        await send_inner({"type": "http.response.start", "status": 200, "headers": []})
        await send_inner({"type": "http.response.body", "body": b"ok"})

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/copilot/from-image",
        "headers": [(b"content-type", b"multipart/form-data; boundary=x")],
    }
    asyncio.run(_ImageBodyLimitMiddleware(inner)(scope, receive, send))

    assert entered is True
    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 413


def test_concurrent_broadcasts_try_a_timed_out_peer_only_once() -> None:
    class SlowWebSocket:
        def __init__(self) -> None:
            self.calls = 0

        async def send_json(self, _payload) -> None:
            self.calls += 1
            await asyncio.Event().wait()

    async def scenario() -> tuple[int, bool]:
        hub = _WebSocketHub(send_timeout=0.01)
        websocket = SlowWebSocket()
        peer = await hub.register("table", websocket)  # type: ignore[arg-type]
        await asyncio.gather(*(hub.broadcast("table", {"version": index}) for index in range(10)))
        return websocket.calls, peer.failed

    calls, failed = asyncio.run(scenario())
    assert calls == 1
    assert failed is True


def test_from_image_rejects_invalid_bytes_even_with_allowed_media(client: TestClient) -> None:
    response = client.post(
        "/copilot/from-image",
        files={"image": ("fake.png", b"not-a-png", "image/png")},
    )
    assert response.status_code == 400


def test_from_image_rejects_excessive_pixel_count(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("POKER_MAX_IMAGE_PIXELS", "100")
    response = client.post(
        "/copilot/from-image",
        files={"image": ("table.png", _png_bytes(), "image/png")},
    )
    assert response.status_code == 413


def test_from_image_normalizes_pillow_decompression_bomb_to_413(client: TestClient) -> None:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)

    hostile = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 20_000, 20_000, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b""))
        + chunk(b"IEND", b"")
    )

    response = client.post(
        "/copilot/from-image",
        files={"image": ("hostile.png", hostile, "image/png")},
    )

    assert response.status_code == 413
    assert "limite seguro" in response.json()["detail"]


def test_from_image_never_authorizes_unvalidated_f1_baseline(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    plausible = RecognizedState(
        hole=["As", "Kh"],
        board=["2c", "3d", "4h"],
        pot=100,
        n_cards=5,
        confidence=0.99,
        card_confidences=[0.99] * 5,
        pot_confidence=0.99,
        n_players=2,
        position="BTN",
        pot_source="ocr",
    )
    monkeypatch.setattr(
        "poker_arena.vision.recognize_table_onnx",
        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()),
    )
    monkeypatch.setattr("poker_arena.vision.recognize_table", lambda *a, **k: plausible)

    response = client.post(
        "/copilot/from-image",
        files={"image": ("table.png", _png_bytes(), "image/png")},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["engine"] == "F1-template"
    assert body["sanity"]["ok"] is False
    assert body["decision"] is None
    assert any("não autoriza decisão" in problem for problem in body["sanity"]["problems"])


def test_f2_uses_manual_active_opponents_not_detected_seated_count(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    detected = RecognizedState(
        hole=["As", "Kh"],
        board=["2c", "3d", "4h"],
        pot=100,
        n_cards=5,
        confidence=0.99,
        card_confidences=[0.99] * 5,
        pot_confidence=0.99,
        n_players=5,
        position="BTN",
        player_count_confidence=0.99,
        position_confidence=0.99,
        pot_source="ocr",
    )
    monkeypatch.setattr("poker_arena.vision.recognize_table_onnx", lambda *_a, **_k: detected)

    response = client.post(
        "/copilot/from-image",
        files={"image": ("table.png", _png_bytes(), "image/png")},
        data={
            "num_opponents": "1",
            "my_stack": "1000",
            "effective_stack": "1000",
            "to_call": "0",
            "in_position": "true",
            "hero_current_bet": "0",
            "current_bet": "0",
            "min_raise_increment": "20",
            "raise_reopened": "true",
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["engine"] == "F2-onnx"
    assert body["detected"]["n_players"] == 5
    assert body["decision"]["num_players"] == 2
    assert any(
        "contexto manual não verificado" in warning for warning in body["sanity"]["warnings"]
    )


def test_f2_forbids_aggression_when_manual_context_says_opponent_is_all_in(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    detected = RecognizedState(
        hole=["As", "Ah"],
        board=["2c", "3d", "4h"],
        pot=100,
        n_cards=5,
        confidence=0.99,
        card_confidences=[0.99] * 5,
        pot_confidence=0.99,
        n_players=2,
        position="SB",
        player_count_confidence=0.99,
        position_confidence=0.99,
        pot_source="ocr",
    )
    monkeypatch.setattr("poker_arena.vision.recognize_table_onnx", lambda *_a, **_k: detected)

    response = client.post(
        "/copilot/from-image",
        files={"image": ("table.png", _png_bytes(), "image/png")},
        data={
            "num_opponents": "1",
            "my_stack": "1000",
            "effective_stack": "0",
            "to_call": "0",
            "in_position": "true",
            "hero_current_bet": "0",
            "current_bet": "0",
            "min_raise_increment": "20",
            "raise_reopened": "true",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["sanity"]["ok"] is True
    assert response.json()["decision"]["recommendation"] == "check"
    assert {item["action"] for item in response.json()["decision"]["options"]} == {"check"}


def test_f2_abstains_when_manual_betting_context_is_incomplete(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    detected = RecognizedState(
        hole=["As", "Ah"],
        board=["2c", "3d", "4h"],
        pot=100,
        n_cards=5,
        confidence=0.99,
        card_confidences=[0.99] * 5,
        pot_confidence=0.99,
        n_players=2,
        position="BTN",
        player_count_confidence=0.99,
        position_confidence=0.99,
        pot_source="ocr",
    )
    monkeypatch.setattr("poker_arena.vision.recognize_table_onnx", lambda *_a, **_k: detected)

    response = client.post(
        "/copilot/from-image",
        files={"image": ("table.png", _png_bytes(), "image/png")},
        data={"num_opponents": "1", "my_stack": "1000", "to_call": "0"},
    )

    assert response.status_code == 200
    assert response.json()["sanity"]["ok"] is False
    assert response.json()["decision"] is None
    assert any("contexto manual" in item for item in response.json()["sanity"]["problems"])


def test_f2_abstains_when_strategic_context_confidence_is_low(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    detected = RecognizedState(
        hole=["As", "Kh"],
        board=["2c", "3d", "4h"],
        pot=100,
        n_cards=5,
        confidence=0.99,
        card_confidences=[0.99] * 5,
        pot_confidence=0.99,
        n_players=5,
        position="BTN",
        player_count_confidence=0.40,
        position_confidence=0.99,
        pot_source="ocr",
    )
    monkeypatch.setattr("poker_arena.vision.recognize_table_onnx", lambda *_a, **_k: detected)

    response = client.post(
        "/copilot/from-image",
        files={"image": ("table.png", _png_bytes(), "image/png")},
        data={"num_opponents": "1"},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["engine"] == "F2-onnx"
    assert body["sanity"]["ok"] is False
    assert body["decision"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "fold", "amount": 1},
        {"type": "check", "amount": 1},
        {"type": "call", "amount": 1},
        {"type": "all_in", "amount": 1},
        {"type": "raise", "amount": 0},
        {"type": "raise", "amount": 1_000_000_001},
    ],
)
def test_action_schema_rejects_ambiguous_amounts(
    client: TestClient, payload: dict[str, object]
) -> None:
    response = client.post("/tables/not-used/actions", json=payload)
    assert response.status_code == 422


def _create_table(client: TestClient) -> str:
    response = client.post(
        "/tables",
        json={"bots": [{"name": "B", "level": "heuristic"}], "seed": 7},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["table_id"])


def test_websocket_rejects_untrusted_origin(client: TestClient) -> None:
    table_id = _create_table(client)
    with (
        pytest.raises(WebSocketDisconnect) as error,
        client.websocket_connect(
            f"/tables/{table_id}/ws",
            headers={"origin": "https://evil.example"},
        ),
    ):
        pass
    assert error.value.code == 4403


def test_websocket_handles_non_object_json(client: TestClient) -> None:
    table_id = _create_table(client)
    with client.websocket_connect(
        f"/tables/{table_id}/ws",
        headers={"origin": "http://localhost:5173"},
    ) as websocket:
        websocket.receive_json()
        websocket.send_json(["fold"])
        response = websocket.receive_json()
        assert response == {"error": "mensagem deve ser um objeto JSON"}


def test_websocket_commands_are_validated_versioned_and_idempotent(
    client: TestClient,
) -> None:
    table_id = _create_table(client)
    with client.websocket_connect(
        f"/tables/{table_id}/ws",
        headers={"origin": "http://localhost:5173"},
    ) as websocket:
        initial = websocket.receive_json()
        assert initial["version"] == 0

        command = {
            "type": "fold",
            "amount": 0,
            "command_id": "ws-fold-1",
            "expected_version": 0,
        }
        websocket.send_json(command)
        first = websocket.receive_json()
        websocket.send_json(command)
        replay = websocket.receive_json()
        assert first == replay
        assert first["version"] == 1

        websocket.send_json({**command, "type": "call"})
        assert websocket.receive_json()["code"] == "idempotency_conflict"

        websocket.send_json({**command, "command_id": "ws-stale"})
        assert websocket.receive_json()["code"] == "version_conflict"

        websocket.send_json({"type": "fold", "amount": 1})
        assert websocket.receive_json()["code"] == "validation_error"


def test_optional_api_token_protects_http_and_websocket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "T" * 32
    monkeypatch.setenv("POKER_WARMUP", "0")
    monkeypatch.setenv("POKER_API_TOKEN", token)
    app = create_app()
    repository = InMemorySessionRepository()
    app.dependency_overrides[get_repository] = lambda: repository
    token_client = TestClient(app)

    assert token_client.get("/health").status_code == 200
    assert token_client.get("/levels").status_code == 401
    local_unauthorized = token_client.get("/levels", headers={"Origin": "http://127.0.0.1:4177"})
    assert local_unauthorized.status_code == 401
    assert local_unauthorized.json() == {"detail": "token de API ausente ou inválido"}
    assert local_unauthorized.headers["access-control-allow-origin"] == "http://127.0.0.1:4177"
    assert "origin" in local_unauthorized.headers["vary"].lower()
    external_unauthorized = token_client.get("/levels", headers={"Origin": "https://evil.example"})
    assert external_unauthorized.status_code == 401
    assert "access-control-allow-origin" not in external_unauthorized.headers
    assert token_client.get("/levels", headers={"X-Poker-Token": token}).status_code == 200
    preflight = token_client.options(
        "/levels",
        headers={
            "Origin": "http://127.0.0.1:4177",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Poker-Token",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://127.0.0.1:4177"
    assert "x-poker-token" in preflight.headers["access-control-allow-headers"].lower()
    assert token_client.options("/levels").status_code == 401

    external_preflight = token_client.options(
        "/levels",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert external_preflight.status_code == 400
    assert "access-control-allow-origin" not in external_preflight.headers

    created = token_client.post(
        "/tables",
        headers={"X-Poker-Token": token},
        json={"bots": [{"name": "B", "level": "heuristic"}], "seed": 7},
    )
    table_id = created.json()["table_id"]
    with (
        pytest.raises(WebSocketDisconnect) as error,
        token_client.websocket_connect(
            f"/tables/{table_id}/ws", headers={"origin": "http://localhost:5173"}
        ),
    ):
        pass
    assert error.value.code == 4401

    with (
        pytest.raises(WebSocketDisconnect) as query_error,
        token_client.websocket_connect(
            f"/tables/{table_id}/ws?token={token}",
            headers={"origin": "http://localhost:5173"},
        ),
    ):
        pass
    assert query_error.value.code == 4401

    with token_client.websocket_connect(
        f"/tables/{table_id}/ws",
        headers={"origin": "http://localhost:5173", "X-Poker-Token": token},
    ) as websocket:
        assert websocket.receive_json()["table_id"] == table_id


def test_weak_api_token_fails_closed_and_degrades_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POKER_WARMUP", "0")
    monkeypatch.setenv("POKER_API_TOKEN", "too-short")
    client = TestClient(create_app())

    assert client.get("/levels", headers={"X-Poker-Token": "too-short"}).status_code == 401
    ready = client.get("/ready")
    assert ready.status_code == 503
    assert ready.json()["status"] == "degraded"
    assert ready.json()["checks"]["api_auth_token"] == "invalid"


def test_request_id_host_and_cors_boundaries(client: TestClient) -> None:
    echoed = client.get("/health", headers={"X-Request-ID": "qa-123"})
    assert echoed.headers["x-request-id"] == "qa-123"

    replaced = client.get("/health", headers={"X-Request-ID": "bad id\n"})
    assert replaced.headers["x-request-id"] != "bad id\n"
    assert len(replaced.headers["x-request-id"]) == 32

    assert client.get("/health", headers={"host": "evil.example"}).status_code == 400
    cors = client.options(
        "/health",
        headers={
            "origin": "https://evil.example",
            "access-control-request-method": "GET",
        },
    )
    assert "access-control-allow-origin" not in cors.headers


def test_unsafe_browser_requests_reject_external_origin_and_fetch_metadata(
    client: TestClient,
) -> None:
    payload = {"bots": [{"name": "B", "level": "heuristic"}], "seed": 17}

    external = client.post(
        "/tables",
        headers={"Origin": "https://evil.example"},
        json=payload,
    )
    assert external.status_code == 403
    assert "origem" in external.json()["detail"]

    cross_site = client.post(
        "/tables",
        headers={"Sec-Fetch-Site": "cross-site"},
        json=payload,
    )
    assert cross_site.status_code == 403
    assert "cross-site" in cross_site.json()["detail"]

    local = client.post(
        "/tables",
        headers={
            "Origin": "http://localhost:5173",
            "Sec-Fetch-Site": "same-site",
        },
        json=payload,
    )
    assert local.status_code == 201

    cli = client.post("/tables", json={**payload, "seed": 18})
    assert cli.status_code == 201


def test_readiness_and_security_headers(client: TestClient) -> None:
    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] in {"ready", "degraded"}
    assert "checks" in ready.json()

    health = client.get("/health")
    assert health.headers["x-content-type-options"] == "nosniff"
    assert health.headers["referrer-policy"] == "no-referrer"
    assert health.headers["x-frame-options"] == "DENY"


def test_readiness_degrades_when_enabled_remote_vlm_has_no_valid_inbound_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import poker_arena.vision as vision_pkg

    monkeypatch.setenv("POKER_WARMUP", "0")
    monkeypatch.setenv("POKER_ENABLE_REMOTE_VLM", "1")
    monkeypatch.delenv("POKER_API_TOKEN", raising=False)
    monkeypatch.setattr(vision_pkg, "vlm_available", lambda: True)

    response = TestClient(create_app()).get("/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["checks"]["remote_vlm_api_token"] == "missing-or-invalid"


def test_readiness_accepts_complete_remote_vlm_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    import poker_arena.vision as vision_pkg

    monkeypatch.setenv("POKER_WARMUP", "0")
    monkeypatch.setenv("POKER_ENABLE_REMOTE_VLM", "1")
    monkeypatch.setenv("POKER_API_TOKEN", "a" * 32)
    monkeypatch.setenv("POKER_REMOTE_VLM_CONSENT_TTL_SECONDS", "600")
    monkeypatch.setattr(vision_pkg, "vlm_available", lambda: True)

    response = TestClient(create_app()).get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["checks"]["remote_vlm"] == "configured"
