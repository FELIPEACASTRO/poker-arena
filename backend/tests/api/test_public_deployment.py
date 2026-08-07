"""Contract tests for the proxy-only public deployment profile."""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from poker_arena.api.app import create_app
from poker_arena.api.dependencies import get_repository
from poker_arena.application import InMemorySessionRepository

PUBLIC_HOST = "poker.example.test"
PUBLIC_ORIGIN = f"https://{PUBLIC_HOST}"
PROXY_USER = "researcher@example.test"
PROXY_TOKEN = "9f" * 32


def _configure_public_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[TestClient, dict[str, str]]:
    secret = tmp_path / "proxy-token"
    secret.write_text(PROXY_TOKEN + "\n", encoding="ascii")
    monkeypatch.setenv("POKER_PUBLIC_DEPLOYMENT", "1")
    monkeypatch.setenv("POKER_ALLOWED_HOSTS", PUBLIC_HOST)
    monkeypatch.setenv("POKER_ALLOWED_ORIGINS", PUBLIC_ORIGIN)
    monkeypatch.setenv("POKER_API_TOKEN_FILE", str(secret.resolve()))
    monkeypatch.setenv("POKER_ROOT_PATH", "/api")
    monkeypatch.delenv("POKER_API_TOKEN", raising=False)
    monkeypatch.setenv("POKER_WARMUP", "0")
    app = create_app()
    repository = InMemorySessionRepository()
    app.dependency_overrides[get_repository] = lambda: repository
    headers = {
        "host": PUBLIC_HOST,
        "origin": PUBLIC_ORIGIN,
        "x-poker-token": PROXY_TOKEN,
        "x-authenticated-user": PROXY_USER,
    }
    return TestClient(app), headers


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("POKER_ALLOWED_HOSTS", "*"),
        ("POKER_ALLOWED_ORIGINS", "http://poker.example.test"),
        ("POKER_ALLOWED_ORIGINS", "https://poker.example.test/path"),
        ("POKER_ALLOWED_ORIGINS", "https://other.example.test"),
        ("POKER_ROOT_PATH", ""),
    ],
)
def test_public_profile_rejects_partial_or_unsafe_configuration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    name: str,
    value: str,
) -> None:
    secret = tmp_path / "proxy-token"
    secret.write_text(PROXY_TOKEN, encoding="ascii")
    monkeypatch.setenv("POKER_PUBLIC_DEPLOYMENT", "1")
    monkeypatch.setenv("POKER_ALLOWED_HOSTS", PUBLIC_HOST)
    monkeypatch.setenv("POKER_ALLOWED_ORIGINS", PUBLIC_ORIGIN)
    monkeypatch.setenv("POKER_API_TOKEN_FILE", str(secret.resolve()))
    monkeypatch.setenv("POKER_ROOT_PATH", "/api")
    monkeypatch.delenv("POKER_API_TOKEN", raising=False)
    monkeypatch.setenv(name, value)

    with pytest.raises(RuntimeError):
        create_app()


def test_public_profile_rejects_missing_or_ambiguous_secret_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("POKER_PUBLIC_DEPLOYMENT", "1")
    monkeypatch.setenv("POKER_ALLOWED_HOSTS", PUBLIC_HOST)
    monkeypatch.setenv("POKER_ALLOWED_ORIGINS", PUBLIC_ORIGIN)
    monkeypatch.setenv("POKER_ROOT_PATH", "/api")
    monkeypatch.delenv("POKER_API_TOKEN_FILE", raising=False)
    monkeypatch.delenv("POKER_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="POKER_API_TOKEN_FILE"):
        create_app()

    secret = tmp_path / "proxy-token"
    secret.write_text(PROXY_TOKEN, encoding="ascii")
    monkeypatch.setenv("POKER_API_TOKEN_FILE", str(secret.resolve()))
    monkeypatch.setenv("POKER_API_TOKEN", PROXY_TOKEN)
    with pytest.raises(RuntimeError, match="não segredo em ambiente"):
        create_app()


def test_public_profile_requires_proxy_secret_and_individual_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client, headers = _configure_public_profile(monkeypatch, tmp_path)

    # Direct container probes remain possible only for liveness/readiness. The gateway
    # protects these paths externally; every application resource is double-gated.
    assert client.get("/health", headers={"host": PUBLIC_HOST}).status_code == 200
    assert client.get("/levels", headers={"host": PUBLIC_HOST}).status_code == 401
    assert (
        client.get(
            "/levels",
            headers={
                "host": PUBLIC_HOST,
                "x-poker-token": PROXY_TOKEN,
            },
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/levels",
            headers={
                "host": PUBLIC_HOST,
                "x-authenticated-user": PROXY_USER,
            },
        ).status_code
        == 401
    )
    assert client.get("/levels", headers=headers).status_code == 200
    invalid_identity = {**headers, "x-authenticated-user": ""}
    assert client.get("/levels", headers=invalid_identity).status_code == 401


def test_public_swagger_uses_gateway_root_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client, headers = _configure_public_profile(monkeypatch, tmp_path)
    docs = client.get("/docs", headers=headers)
    assert docs.status_code == 200
    assert "url: '/api/openapi.json'" in docs.text
    contract = client.get("/openapi.json", headers=headers).json()
    assert contract["servers"] == [
        {"url": "/api", "description": "Gateway público autenticado"}
    ]
    assert contract["components"]["securitySchemes"]["EdgeSession"] == {
        "type": "apiKey",
        "in": "cookie",
        "name": "__Host-poker_auth",
        "description": (
            "Sessão individual OIDC emitida pelo oauth2-proxy no gateway; "
            "não é criada nem lida diretamente pelo FastAPI."
        ),
    }
    assert contract["security"] == [{"EdgeSession": []}]
    assert contract["paths"]["/levels"]["get"]["security"] == [{"EdgeSession": []}]
    assert "não são multi-tenant" in contract["x-public-deployment-trust"]


def test_public_profile_allows_only_the_exact_https_browser_origin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client, headers = _configure_public_profile(monkeypatch, tmp_path)
    payload = {"bots": [{"name": "B", "level": "heuristic"}], "seed": 17}

    accepted = client.post("/tables", headers=headers, json=payload)
    assert accepted.status_code == 201, accepted.text

    rejected = client.post(
        "/tables",
        headers={**headers, "origin": "https://evil.example"},
        json={**payload, "seed": 18},
    )
    assert rejected.status_code == 403
    assert "access-control-allow-origin" not in rejected.headers

    preflight = client.options(
        "/levels",
        headers={
            "host": PUBLIC_HOST,
            "origin": PUBLIC_ORIGIN,
            "access-control-request-method": "GET",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == PUBLIC_ORIGIN


def test_public_websocket_requires_exact_origin_secret_and_user(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client, headers = _configure_public_profile(monkeypatch, tmp_path)
    table = client.post(
        "/tables",
        headers=headers,
        json={"bots": [{"name": "B", "level": "heuristic"}], "seed": 19},
    )
    table_id = table.json()["table_id"]

    with (
        pytest.raises(WebSocketDisconnect) as missing_user,
        client.websocket_connect(
            f"/tables/{table_id}/ws",
            headers={
                "host": PUBLIC_HOST,
                "origin": PUBLIC_ORIGIN,
                "x-poker-token": PROXY_TOKEN,
            },
        ),
    ):
        pass
    assert missing_user.value.code == 4401

    with (
        pytest.raises(WebSocketDisconnect) as wrong_origin,
        client.websocket_connect(
            f"/tables/{table_id}/ws",
            headers={**headers, "origin": "https://evil.example"},
        ),
    ):
        pass
    assert wrong_origin.value.code == 4403

    with client.websocket_connect(
        f"/tables/{table_id}/ws", headers=headers
    ) as websocket:
        assert websocket.receive_json()["table_id"] == table_id


def test_public_profile_rejects_relative_secret_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POKER_PUBLIC_DEPLOYMENT", "1")
    monkeypatch.setenv("POKER_ALLOWED_HOSTS", PUBLIC_HOST)
    monkeypatch.setenv("POKER_ALLOWED_ORIGINS", PUBLIC_ORIGIN)
    monkeypatch.setenv("POKER_ROOT_PATH", "/api")
    monkeypatch.setenv("POKER_API_TOKEN_FILE", os.path.join("relative", "token"))
    monkeypatch.delenv("POKER_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="absoluto"):
        create_app()


def test_versioned_public_profile_passes_its_structural_gate(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = Path(__file__).resolve().parents[3] / "deploy" / "production"
    monkeypatch.setattr(sys, "argv", [str(profile / "validate_profile.py")])
    runpy.run_path(str(profile / "validate_profile.py"), run_name="__main__")
    assert capsys.readouterr().out.strip() == "PRODUCTION_PROFILE_STATIC_OK"

    monkeypatch.setattr(
        sys, "argv", [str(profile / "validate_profile.py"), "--homologation"]
    )
    with pytest.raises(AssertionError, match="fixe todas as imagens por digest"):
        runpy.run_path(str(profile / "validate_profile.py"), run_name="__main__")
