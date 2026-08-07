from __future__ import annotations

import hashlib
import json
import socket
from pathlib import Path

import pytest

import scripts.platform_inventory as inventory
from scripts.platform_inventory import _request, build_receipt, main, parse_platforms

CATALOGUE = """\
# Catálogo

## 1. Gerais

| Nome | URL |
|---|---|
| arXiv | [https://arxiv.org/](https://arxiv.org/) |
| Repetido | [https://arxiv.org/](https://arxiv.org/) |

## 2. Computação

| Nome | URL |
|---|---|
| OpenReview | [https://openreview.net/](https://openreview.net/) |

## Fontes-base do levantamento

| Nome | URL |
|---|---|
| Ignorado | [https://example.invalid/](https://example.invalid/) |
"""


def test_parser_keeps_sections_and_deduplicates_exact_urls() -> None:
    platforms = parse_platforms(CATALOGUE)

    assert [(item.section, item.name, item.url) for item in platforms] == [
        (1, "arXiv", "https://arxiv.org/"),
        (2, "OpenReview", "https://openreview.net/"),
    ]
    assert all(len(item.inventory_id) == 16 for item in platforms)


def test_receipt_records_source_hash_counts_and_no_probe(tmp_path: Path) -> None:
    source = tmp_path / "catalogue.md"
    source.write_text(CATALOGUE, encoding="utf-8")
    platforms = parse_platforms(CATALOGUE)

    receipt = build_receipt(source, platforms, generated_at="2026-07-17T00:00:00+00:00")

    assert receipt["platform_count"] == 2
    assert receipt["section_counts"] == {"1": 1, "2": 1}
    assert receipt["source"]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert all("probe" not in item for item in receipt["platforms"])


def test_cli_generates_utf8_json_without_network(tmp_path: Path) -> None:
    source = tmp_path / "catálogo.md"
    output = tmp_path / "receipt.json"
    source.write_text(CATALOGUE, encoding="utf-8")

    assert main([str(source), "--output", str(output)]) == 0
    parsed = json.loads(output.read_text(encoding="utf-8"))
    assert parsed["platform_count"] == 2
    assert parsed["platforms"][0]["name"] == "arXiv"


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://localhost/admin",
        "http://127.0.0.1:8000/health",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "https://user:password@example.com/",
        "https://example.com/?token=secret",
        "https://example.com/#fragment",
    ],
)
def test_probe_rejects_non_public_or_credentialed_urls_before_network(url: str) -> None:
    with pytest.raises(ValueError, match="public|credentials|query|fragment"):
        _request(url, "HEAD", 0.1)


def test_probe_pins_public_dns_and_does_not_use_environment_proxy(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Headers(dict):
        pass

    class Response:
        status = 200
        reason = "OK"
        headers = Headers()

        def getheader(self, _name):
            return None

        def read(self, _limit):
            return b""

    class Connection:
        def __init__(self, host, port, connect_ip, timeout):
            captured.update(host=host, port=port, connect_ip=connect_ip, timeout=timeout)

        def request(self, method, target, headers):
            captured.update(method=method, target=target, headers=headers)

        def getresponse(self):
            return Response()

        def close(self):
            captured["closed"] = True

    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setattr(
        inventory.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )
    monkeypatch.setattr(inventory, "_PinnedHTTPSConnection", Connection)

    status, final_url = _request("https://platform.example.test/root", "HEAD", 1.5)

    assert (status, final_url) == (200, "https://platform.example.test/root")
    assert captured["connect_ip"] == "93.184.216.34"
    assert captured["target"] == "/root"
    assert captured["closed"] is True
