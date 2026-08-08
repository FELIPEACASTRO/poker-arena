from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest
from fastapi.openapi.models import OpenAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from poker_arena.api.app import create_app

ROOT = Path(__file__).resolve().parents[3]
DOCS = ROOT / "api-docs"
GENERATOR = DOCS / "generate.py"
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}
INSOMNIA_VARIABLE = re.compile(r"\{\{ _\.([A-Za-z_][A-Za-z0-9_]*) \}\}")
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bhf_[A-Za-z0-9]{20,}\b"),
    re.compile(r"https?://[^/\s:@]+:[^@\s]+@"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~-]{20,}\b", re.IGNORECASE),
)
EXPECTED_VENDOR_FILES = {
    "LICENSE": (
        11358,
        "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
    ),
    "NOTICE": (
        55,
        "0d20d1adef18aee3f40dd258172155521ce702ac445cb5f7b7d60ed32dad2fb2",
    ),
    "swagger-ui-bundle.js": (
        1452753,
        "c2e4a9ef08144839ff47c14202063ecfe4e59e70a4e7154a26bd50d880c88ba1",
    ),
    "swagger-ui-bundle.js.LICENSE.txt": (
        298,
        "314861a55a8edcac71b2c486ab627fa8a0e108c8dd1a766c807668fefd800fb4",
    ),
    "swagger-ui.css": (
        152071,
        "40170f0ee859d17f92131ba707329a88a070e4f66874d11365e9a77d232f6117",
    ),
}

EXPECTED_REDOC_VENDOR_FILES = {
    "REDOC_LICENSE": (
        1091,
        "d3026d549cf68ab7355bcfa85877bf8f845b3334a7efbfdc63936432fb34ff0e",
    ),
    "redoc.standalone.js": (
        1097271,
        "1320f442151c57c447d3b70c7ffc6c4f86d08464020fe34c8cc5d3164e9944f0",
    ),
    "redoc.standalone.js.LICENSE.txt": (
        2727,
        "469cc94b600aac09643f70e167cd1f66f24301ebb546532fad5db7c60f7b30d0",
    ),
}


def _load_generator():
    spec = importlib.util.spec_from_file_location("poker_api_docs_generator", GENERATOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _operations(openapi: dict[str, Any]) -> set[tuple[str, str]]:
    return {
        (method.upper(), path)
        for path, item in openapi["paths"].items()
        for method in item
        if method in HTTP_METHODS
    }


def _operation_rows(openapi: dict[str, Any]):
    for path, item in openapi["paths"].items():
        for method, operation in item.items():
            if method in HTTP_METHODS:
                yield method.upper(), path, operation


def _insomnia_path(url: str) -> str:
    path = url.removeprefix("{{ _.base_url }}")
    return INSOMNIA_VARIABLE.sub(lambda match: "{" + match.group(1) + "}", path)


def _resolve_pointer(document: dict[str, Any], ref: str) -> Any:
    assert ref.startswith("#/"), f"referência externa ou inválida: {ref}"
    current: Any = document
    for raw_part in ref[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        current = current[part]
    return current


def _walk_refs(value: Any):
    if isinstance(value, dict):
        if "$ref" in value:
            yield value["$ref"]
        for child in value.values():
            yield from _walk_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_refs(child)


def _request_by_operation(insomnia: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (resource["method"], _insomnia_path(resource["url"])): resource
        for resource in insomnia["resources"]
        if resource["_type"] == "request"
    }


def test_generated_contract_is_complete_deterministic_and_safe():
    generator = _load_generator()

    first = generator.build_artifacts()
    second = generator.build_artifacts()
    assert first == second

    openapi, insomnia, swagger = first
    assert openapi == generator.app.openapi()
    generated_requests = _request_by_operation(insomnia)
    assert set(generated_requests) == _operations(openapi)
    assert _operations(openapi) == _operations(generator.app.openapi())
    assert openapi["openapi"] == "3.1.0"
    assert openapi["info"]["version"] == "0.2.0"
    assert openapi["servers"] == [generator.LOCAL_SERVER]
    assert OpenAPI.model_validate(openapi).openapi == "3.1.0"

    # O enriquecimento não pode alterar os modelos derivados do FastAPI.
    live_schemas = generator.app.openapi()["components"]["schemas"]
    for name, schema in live_schemas.items():
        expected = json.loads(json.dumps(schema))
        generator._normalize_schema_examples(expected)
        assert openapi["components"]["schemas"][name] == expected

    operation_ids = [operation["operationId"] for _, _, operation in _operation_rows(openapi)]
    assert len(operation_ids) == len(set(operation_ids))
    declared_tags = {tag["name"] for tag in openapi["tags"]}
    for _, _, operation in _operation_rows(openapi):
        assert operation.get("summary")
        assert operation.get("description")
        assert set(operation.get("tags", [])) <= declared_tags
        assert any(str(status).startswith("2") for status in operation["responses"])

    for ref in _walk_refs(openapi):
        assert _resolve_pointer(openapi, ref) is not None

    ids = {resource["_id"] for resource in insomnia["resources"]}
    assert len(ids) == len(insomnia["resources"])
    for resource in insomnia["resources"]:
        if "parentId" in resource:
            assert resource["parentId"] in ids
    assert sum(r["_type"] == "websocket_request" for r in insomnia["resources"]) == 1
    assert insomnia["__export_date"] == "1970-01-01T00:00:00.000Z"

    # A especificação é Base64, não JavaScript interpolado/executável.
    encoded = re.search(r'JSON\.parse\(atob\("([A-Za-z0-9+/=]+)"\)\)', swagger)
    assert encoded
    embedded = json.loads(base64.b64decode(encoded.group(1)).decode("ascii"))
    assert embedded == openapi
    assert "const spec = {" not in swagger
    assert 'location.protocol === "http:"' in swagger
    assert 'location.protocol === "https:"' in swagger
    assert "persistAuthorization:false" in swagger


def test_exported_security_errors_and_concurrency_headers_match_runtime_contract():
    generator = _load_generator()
    openapi, insomnia, _ = generator.build_artifacts()
    requests = _request_by_operation(insomnia)

    assert {"PokerToken", "PokerBearer"} <= set(openapi["components"]["securitySchemes"])
    guaranteed_headers = {
        "Cache-Control",
        "Content-Security-Policy",
        "Referrer-Policy",
        "X-Content-Type-Options",
        "X-Frame-Options",
        "X-Request-ID",
    }
    for method, path, operation in _operation_rows(openapi):
        protected = path not in generator.PUBLIC_PATHS
        strict_remote_auth = path == generator.REMOTE_VLM_CONSENT_PATH
        if strict_remote_auth:
            assert operation["security"] == [
                {"PokerToken": []},
                {"PokerBearer": []},
            ]
        elif protected:
            assert operation["security"] == [{}, {"PokerToken": []}, {"PokerBearer": []}]
            assert "401" in operation["responses"]
            assert any(
                header["name"] == "X-Poker-Token" for header in requests[method, path]["headers"]
            )
        else:
            assert operation["security"] == []
            assert all(
                header["name"] != "X-Poker-Token" for header in requests[method, path]["headers"]
            )

        for response in operation["responses"].values():
            assert guaranteed_headers <= set(response["headers"])

        host_error = operation["responses"]["400"]
        assert host_error["content"]["text/plain"]["schema"] == {"type": "string"}

        header_parameters: set[str] = set()
        for raw_parameter in operation.get("parameters", []):
            parameter = (
                _resolve_pointer(openapi, raw_parameter["$ref"])
                if "$ref" in raw_parameter
                else raw_parameter
            )
            if parameter.get("in") == "header":
                header_parameters.add(parameter["name"])
        generated_headers = {header["name"] for header in requests[method, path]["headers"]}
        assert header_parameters <= generated_headers
        if protected:
            assert {"Authorization", "X-Poker-Token"} <= generated_headers
        if strict_remote_auth:
            token_headers = {
                header["name"]: header
                for header in requests[method, path]["headers"]
                if header["name"] in {"Authorization", "X-Poker-Token"}
            }
            assert token_headers["X-Poker-Token"]["disabled"] is False
            assert token_headers["Authorization"]["disabled"] is True

        for status, response in operation["responses"].items():
            if str(status).startswith("4") and status != "422":
                live_response = generator.app.openapi()["paths"][path][method.lower()][
                    "responses"
                ].get(status)
                if status != "400" or live_response is not None:
                    json_error = response.get("content", {}).get("application/json")
                    if json_error is None:
                        assert status == "400"
                        assert "text/plain" in response["content"]
                        continue
                    schema = json_error["schema"]
                    assert schema == {"$ref": "#/components/schemas/HttpError"}

    create = openapi["paths"]["/tables"]["post"]
    create_headers = {
        item.get("name") for item in create["parameters"] if item.get("in") == "header"
    }
    assert "Idempotency-Key" in create_headers
    assert "If-Match" not in create_headers  # o runtime rejeita If-Match na criação

    for _method, _path, operation in _operation_rows(openapi):
        has_idempotency = any(
            item.get("name") == "Idempotency-Key" for item in operation.get("parameters", [])
        )
        if has_idempotency:
            assert "409" in operation["responses"]

        for response in operation["responses"].values():
            schema = response.get("content", {}).get("application/json", {}).get("schema")
            if schema == {"$ref": "#/components/schemas/TableStateResponse"}:
                assert {
                    "ETag",
                    "X-Idempotent-Replay",
                    "X-Request-ID",
                    "X-Session-Version",
                } <= set(response["headers"])

    image_responses = openapi["paths"]["/copilot/from-image"]["post"]["responses"]
    assert {"400", "401", "403", "413", "415", "422"} <= set(image_responses)
    assert "divergente do MIME declarado" in image_responses["415"]["description"]

    for method, _path, operation in _operation_rows(openapi):
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            assert "403" in operation["responses"]
    assert "503" in openapi["paths"]["/ready"]["get"]["responses"]
    ready_200 = openapi["paths"]["/ready"]["get"]["responses"]["200"]["content"]
    ready_503 = openapi["paths"]["/ready"]["get"]["responses"]["503"]["content"]
    assert ready_503 == ready_200
    consent = openapi["paths"]["/copilot/remote-vlm/consent-sessions"]
    assert "503" in consent["post"]["responses"]
    assert "503" in consent["delete"]["responses"]


def test_documented_middleware_headers_and_host_error_match_live_app(monkeypatch):
    generator = _load_generator()
    monkeypatch.setenv("POKER_WARMUP", "0")
    monkeypatch.delenv("POKER_API_TOKEN", raising=False)

    with TestClient(generator.app) as client:
        healthy = client.get("/health")
        assert healthy.status_code == 200
        expected = {
            "cache-control": "no-store",
            "referrer-policy": "no-referrer",
            "x-content-type-options": "nosniff",
            "x-frame-options": "DENY",
        }
        for name, value in expected.items():
            assert healthy.headers[name] == value
        assert healthy.headers["content-security-policy"].startswith("default-src 'self'")
        assert healthy.headers["x-request-id"]

        rejected = client.get("/levels", headers={"Host": "outside.invalid"})
        assert rejected.status_code == 400
        assert rejected.headers["content-type"].startswith("text/plain")
        assert rejected.text == "Invalid host header"
        for name, value in expected.items():
            assert rejected.headers[name] == value

        token = "T" * 32
        monkeypatch.setenv("POKER_API_TOKEN", token)
        unauthorized = client.get("/levels")
        assert unauthorized.status_code == 401
        assert unauthorized.json() == {"detail": "token de API ausente ou inválido"}
        assert unauthorized.headers["x-request-id"]
        authorized = client.get("/levels", headers={"Authorization": f"Bearer {token}"})
        assert authorized.status_code == 200


def test_insomnia_examples_and_variables_are_derived_and_valid():
    generator = _load_generator()
    openapi, insomnia, _ = generator.build_artifacts()
    requests = _request_by_operation(insomnia)
    environment = next(r for r in insomnia["resources"] if r["_type"] == "environment")["data"]

    variables_used = {
        match.group(1)
        for resource in insomnia["resources"]
        for match in INSOMNIA_VARIABLE.finditer(json.dumps(resource, ensure_ascii=False))
    }
    assert variables_used <= set(environment)
    assert environment["api_token"] == ""
    assert environment["request_id"] == ""
    assert environment["base_url"] == "http://127.0.0.1:8000"
    assert environment["ws_url"] == "ws://127.0.0.1:8000"

    app_routes = {
        (method, route.path): route
        for route in generator.app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }
    for method, path, operation in _operation_rows(openapi):
        request = requests[method, path]
        content = operation.get("requestBody", {}).get("content", {})
        if "application/json" not in content:
            continue
        payload = json.loads(request["body"]["text"])
        route = app_routes[method, path]
        assert route.body_field is not None
        _validated, errors = route.body_field.validate(payload, {}, loc=("body",))
        assert not errors

    multipart = requests["POST", "/copilot/from-image"]["body"]["params"]
    multipart_schema = _resolve_pointer(
        openapi,
        openapi["paths"]["/copilot/from-image"]["post"]["requestBody"]["content"][
            "multipart/form-data"
        ]["schema"]["$ref"],
    )
    assert {item["name"] for item in multipart} == set(multipart_schema["properties"])
    image = next(item for item in multipart if item["name"] == "image")
    assert image["type"] == "file" and not image.get("disabled", False)


def test_live_openapi_and_exported_contract_are_identical():
    generator = _load_generator()
    exported, _, _ = generator.build_artifacts()

    live = TestClient(generator.app).get("/openapi.json")

    assert live.status_code == 200
    assert live.json() == exported


def test_insomnia_review_hand_example_is_semantically_executable():
    generator = _load_generator()
    _, insomnia, _ = generator.build_artifacts()
    request = _request_by_operation(insomnia)["POST", "/copilot/review-hand"]
    payload = json.loads(request["body"]["text"])

    response = TestClient(generator.app).post("/copilot/review-hand", json=payload)

    assert response.status_code == 200, response.text
    assert response.json()["total"] >= 1


def test_generated_json_contains_no_credentials():
    generator = _load_generator()
    openapi, insomnia, _ = generator.build_artifacts()
    text = json.dumps({"openapi": openapi, "insomnia": insomnia}, ensure_ascii=False)
    for pattern in SECRET_PATTERNS:
        assert not pattern.search(text), pattern.pattern


def test_committed_artifacts_match_generator_byte_for_byte(tmp_path):
    generator = _load_generator()
    generator.write_artifacts(tmp_path)

    for name in ("openapi.json", "insomnia.json", "swagger.html"):
        assert (DOCS / name).read_bytes() == (tmp_path / name).read_bytes(), (
            f"{name} está desatualizado; rode backend/.venv/Scripts/python.exe api-docs/generate.py"
        )


def test_write_artifacts_round_trips_json(tmp_path):
    generator = _load_generator()
    generator.write_artifacts(tmp_path)

    openapi = json.loads((tmp_path / "openapi.json").read_text(encoding="utf-8"))
    insomnia = json.loads((tmp_path / "insomnia.json").read_text(encoding="utf-8"))
    assert _operations(openapi)
    assert insomnia["__export_source"] == "poker-arena:generate.py"
    swagger = (tmp_path / "swagger.html").read_text(encoding="utf-8")
    assert "./vendor/swagger-ui.css" in swagger
    assert "./vendor/swagger-ui-bundle.js" in swagger
    assert (DOCS / "vendor" / "swagger-ui.css").stat().st_size > 0
    assert (DOCS / "vendor" / "swagger-ui-bundle.js").stat().st_size > 0


def test_vendored_swagger_has_pinned_provenance_license_and_hashes():
    vendor = DOCS / "vendor"
    receipt = json.loads((vendor / "receipt.json").read_text(encoding="utf-8"))

    assert receipt["schema"] == "poker-arena-vendored-asset-receipt-v1"
    assert receipt["component"] == {
        "license": "Apache-2.0",
        "name": "Swagger UI",
        "package": "swagger-ui-dist",
        "source_repository": "https://github.com/swagger-api/swagger-ui",
        "version": "5.17.14",
    }
    assert receipt["origin"]["tarball_sha256"] == (
        "c57badf459aa6e65cc036b3862d0502a63f9a22546407ffcb0e64f85f816bb28"
    )
    entries = {entry["path"]: entry for entry in receipt["files"]}
    assert set(entries) == set(EXPECTED_VENDOR_FILES)

    for name, (expected_size, expected_hash) in EXPECTED_VENDOR_FILES.items():
        payload = (vendor / name).read_bytes()
        assert len(payload) == expected_size
        assert hashlib.sha256(payload).hexdigest() == expected_hash
        assert entries[name]["bytes"] == expected_size
        assert entries[name]["sha256"] == expected_hash

    bundle = (vendor / "swagger-ui-bundle.js").read_text(encoding="utf-8", errors="strict")
    assert "swagger-ui-bundle.js.LICENSE.txt" in bundle[:200]
    assert "Apache License" in (vendor / "LICENSE").read_text(encoding="utf-8")
    assert "SmartBear Software Inc." in (vendor / "NOTICE").read_text(encoding="utf-8")


def test_vendored_redoc_has_pinned_provenance_license_and_hashes():
    vendor = DOCS / "vendor"
    receipt = json.loads((vendor / "redoc-receipt.json").read_text(encoding="utf-8"))

    assert receipt["schema"] == "poker-arena-vendored-redoc-receipt-v1"
    assert receipt["component"] == {
        "license": "MIT",
        "name": "ReDoc",
        "package": "redoc",
        "source_repository": "https://github.com/Redocly/redoc",
        "version": "2.5.3",
    }
    assert receipt["origin"]["tarball_sha256"] == (
        "e09cc6eb1af62e493e92ebff1ff98b5917ff4018f24ef9be91a3d97998987a73"
    )
    entries = {entry["path"]: entry for entry in receipt["files"]}
    assert set(entries) == set(EXPECTED_REDOC_VENDOR_FILES)
    for name, (expected_size, expected_hash) in EXPECTED_REDOC_VENDOR_FILES.items():
        payload = (vendor / name).read_bytes()
        assert len(payload) == expected_size
        assert hashlib.sha256(payload).hexdigest() == expected_hash
        assert entries[name]["bytes"] == expected_size
        assert entries[name]["sha256"] == expected_hash
    assert "MIT License" in (vendor / "REDOC_LICENSE").read_text(encoding="utf-8")


def test_runtime_docs_are_local_csp_compatible_and_assets_are_public(monkeypatch):
    monkeypatch.setenv("POKER_WARMUP", "0")
    monkeypatch.setenv("POKER_API_TOKEN", "d" * 32)
    with TestClient(create_app()) as client:
        swagger = client.get("/docs")
        redoc = client.get("/redoc")

        assert swagger.status_code == 200
        assert redoc.status_code == 200
        assert "https://" not in swagger.text
        assert "https://" not in redoc.text
        assert 'href="/docs-assets/swagger-ui.css"' in swagger.text
        assert 'src="/docs-assets/swagger-ui-bundle.js"' in swagger.text
        assert 'src="/docs-assets/redoc.standalone.js"' in redoc.text
        assert '<redoc spec-url="/openapi.json"' in redoc.text
        assert 'id="redoc-local-image-guard"' in redoc.text
        assert "worker-src 'self' blob:" in redoc.headers["content-security-policy"]
        assert "url: '/openapi.json'" in swagger.text
        assert 'spec-url="/openapi.json"' in redoc.text

        for path in (
            "/docs-assets/swagger-ui.css",
            "/docs-assets/swagger-ui-bundle.js",
            "/docs-assets/redoc.standalone.js",
        ):
            asset = client.get(path)
            assert asset.status_code == 200
            assert len(asset.content) > 100_000


def test_vendored_swagger_hash_gate_rejects_asset_tampering(tmp_path):
    generator = _load_generator()
    copied_vendor = tmp_path / "vendor"
    shutil.copytree(DOCS / "vendor", copied_vendor)
    asset = copied_vendor / "swagger-ui.css"
    asset.write_bytes(asset.read_bytes() + b" ")

    with pytest.raises(ValueError, match="Swagger"):
        generator._validate_vendor_assets(copied_vendor)


def test_vendored_redoc_hash_gate_rejects_asset_tampering(tmp_path):
    generator = _load_generator()
    copied_vendor = tmp_path / "vendor"
    shutil.copytree(DOCS / "vendor", copied_vendor)
    asset = copied_vendor / "redoc.standalone.js"
    asset.write_bytes(asset.read_bytes() + b" ")

    with pytest.raises(ValueError, match="ReDoc"):
        generator._validate_redoc_assets(copied_vendor)


def test_check_mode_detects_drift_without_mutating_files(tmp_path):
    generator = _load_generator()
    generator.write_artifacts(tmp_path)

    assert generator.main(["--check", "--output-dir", str(tmp_path)]) == 0
    target = tmp_path / "openapi.json"
    target.write_bytes(target.read_bytes() + b" ")
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}

    assert generator.main(["--check", "--output-dir", str(tmp_path)]) == 1
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before
