"""Dependency-free structural gate for the public deployment profile.

This does not replace `docker compose config`, image scanning, or a real TLS/OIDC
handshake.  It catches security controls accidentally removed from the versioned files.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def _read(relative: str) -> str:
    path = ROOT / relative
    if not path.is_file():
        raise AssertionError(f"arquivo obrigatório ausente: {relative}")
    return path.read_text(encoding="utf-8")


def _service_block(compose: str, name: str, next_name: str | None) -> str:
    end = rf"(?=^  {re.escape(next_name)}:|^networks:)" if next_name else r"(?=^networks:)"
    match = re.search(rf"^  {re.escape(name)}:\n(?P<body>.*?){end}", compose, re.M | re.S)
    if match is None:
        raise AssertionError(f"serviço ausente: {name}")
    return match.group("body")


def validate(*, homologation: bool = False) -> None:
    compose = _read("docker-compose.production.yml")
    nginx = _read("gateway/templates/default.conf.template")
    nginx_main = _read("gateway/nginx.conf")
    secret_loader = _read("gateway/15-poker-secrets.envsh")
    oauth_example = _read("oauth2-proxy.cfg.example")
    backend_image = _read("backend.Dockerfile")
    gateway_image = _read("gateway/Dockerfile")
    backend_security = (ROOT.parents[1] / "backend" / "poker_arena" / "api" / "app.py").read_text(
        encoding="utf-8"
    )

    gateway = _service_block(compose, "gateway", "oauth2-proxy")
    oauth = _service_block(compose, "oauth2-proxy", "backend")
    backend = _service_block(compose, "backend", None)

    assert '"80:8080"' in gateway and '"443:8443"' in gateway
    assert "ports:" not in oauth and "ports:" not in backend
    assert "POKER_PUBLIC_DEPLOYMENT: \"1\"" in backend
    assert "POKER_API_TOKEN_FILE: /run/secrets/proxy_shared_secret" in backend
    assert "POKER_ROOT_PATH: /api" in backend
    assert "headers={'Host': os.environ['POKER_ALLOWED_HOSTS']}" in backend
    assert "POKER_API_TOKEN:" not in compose
    assert "read_only: true" in gateway and "read_only: true" in oauth and "read_only: true" in backend
    assert compose.count("cap_drop: [ALL]") == 3
    assert "private:\n    internal: true" in compose
    assert "networks: [private, auth-egress]" in oauth
    for required in (
        "POKER_PROXY_SHARED_SECRET_FILE",
        "POKER_TLS_FULLCHAIN_FILE",
        "POKER_TLS_PRIVATE_KEY_FILE",
        "POKER_OAUTH2_PROXY_CONFIG_FILE",
    ):
        assert required in compose

    for required in (
        "ssl_protocols TLSv1.2 TLSv1.3",
        "Strict-Transport-Security",
        "auth_request /_oauth2_auth",
        "limit_req zone=application_per_ip",
        "proxy_set_header X-Authenticated-User $authenticated_user",
        'proxy_set_header X-Poker-Token "${POKER_PROXY_SHARED_SECRET}"',
        "proxy_set_header Upgrade $http_upgrade",
        "proxy_set_header Connection $connection_upgrade",
        "Retry-After",
    ):
        assert required in nginx
    assert "limit_req_zone" in nginx_main and "limit_conn_zone" in nginx_main
    assert "$request_method $uri" in nginx_main
    assert "$request\"" not in nginx_main
    assert "$args" not in nginx_main and "$request_uri" not in nginx_main
    assert "64 caracteres" in secret_loader and "*[!0-9a-fA-F]*" in secret_loader
    assert "POKER_PUBLIC_HOST inválido" in secret_loader and "*[!a-z0-9.-]*" in secret_loader
    assert "INJECT_BY_SECRET_MANAGER" in oauth_example
    assert "cookie_secure = true" in oauth_example
    assert "set_xauthrequest = true" in oauth_example
    assert "request_logging = false" in oauth_example
    assert "auth_logging = false" in oauth_example
    assert "email_domains = [\"*\"]" not in oauth_example
    assert "USER 10001:10001" in backend_image
    assert "USER 101:101" in gateway_image
    assert "uv==0.11.3" in backend_image
    assert "nginx:1.30.2-alpine" in gateway_image
    assert "quay.io/oauth2-proxy/oauth2-proxy:v7.15.2" in compose
    assert '_proxy_user_valid(request.headers.get("x-authenticated-user"))' in backend_security
    assert '_proxy_user_valid(websocket.headers.get("x-authenticated-user"))' in backend_security

    images = re.findall(r"^\s*(?:FROM|image:)\s+([^\s]+)", compose + backend_image + gateway_image, re.M)
    assert images and all(":latest" not in image and image != "latest" for image in images)
    if homologation and any("@sha256:" not in image for image in images):
        raise AssertionError("homologação bloqueada: fixe todas as imagens por digest sha256")
    print("PRODUCTION_PROFILE_HOMOLOGATION_OK" if homologation else "PRODUCTION_PROFILE_STATIC_OK")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--homologation", action="store_true")
    args = parser.parse_args()
    validate(homologation=args.homologation)
