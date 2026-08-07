"""Canonical OpenAPI projection shared by the live app and offline artifacts.

FastAPI derives route bodies and response models, while authentication and response
headers are implemented by middleware.  Keeping this projection in the backend makes
``/openapi.json`` the same contract consumed by the artifact generator.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

HTTP_METHODS = ("get", "post", "put", "patch", "delete", "options", "head")
LOCAL_SERVER = {"url": "http://127.0.0.1:8000", "description": "Servidor local"}
PUBLIC_PATHS = frozenset({"/health", "/ready"})
REMOTE_VLM_CONSENT_PATH = "/copilot/remote-vlm/consent-sessions"
TABLE_STATE_REF = "#/components/schemas/TableStateResponse"

ERROR_DESCRIPTIONS = {
    "403": "Requisição mutável de navegador bloqueada por Origin/Sec-Fetch-Site.",
    "503": "Dependência habilitada, mas ausente ou mal configurada.",
    "401": "Token de API ausente ou inválido quando `POKER_API_TOKEN` está configurado.",
    "409": (
        "Conflito de versão, reutilização incompatível ou resultado expirado de "
        "`Idempotency-Key`. Uma chave expirada é rejeitada sem repetir o efeito."
    ),
    "413": "Imagem maior que o limite configurado de bytes ou pixels.",
    "415": "Tipo de imagem não permitido; use PNG, JPEG ou WebP.",
}

SECURITY_RESPONSE_HEADERS = {
    "Cache-Control": "CacheControl",
    "Content-Security-Policy": "ContentSecurityPolicy",
    "Referrer-Policy": "ReferrerPolicy",
    "X-Content-Type-Options": "ContentTypeOptions",
    "X-Frame-Options": "FrameOptions",
}


def operation_rows(spec: dict[str, Any]) -> Iterator[tuple[str, str, dict[str, Any]]]:
    for path in sorted(spec["paths"]):
        for method in HTTP_METHODS:
            operation = spec["paths"][path].get(method)
            if operation is not None:
                yield method.upper(), path, operation


def normalize_schema_examples(value: Any) -> None:
    """Convert Pydantic named-example wrappers into valid JSON Schema examples."""

    if isinstance(value, dict):
        examples = value.get("examples")
        if (
            isinstance(examples, list)
            and examples
            and all(
                isinstance(item, dict)
                and "value" in item
                and set(item) <= {"description", "summary", "value"}
                for item in examples
            )
        ):
            summaries = [item.get("summary", "") for item in examples]
            value["examples"] = [item["value"] for item in examples]
            if any(summaries):
                value["x-example-summaries"] = summaries
        for child in value.values():
            normalize_schema_examples(child)
    elif isinstance(value, list):
        for child in value:
            normalize_schema_examples(child)


def _error_content() -> dict[str, Any]:
    return {
        "application/json": {
            "schema": {"$ref": "#/components/schemas/HttpError"},
            "example": {"detail": "descrição objetiva do erro"},
        }
    }


def _host_error_content() -> dict[str, Any]:
    return {
        "text/plain": {
            "example": "Invalid host header",
            "schema": {"type": "string"},
        }
    }


def _merge_content(target: dict[str, Any], additions: dict[str, Any]) -> None:
    content = target.setdefault("content", {})
    for media_type, media in additions.items():
        content.setdefault(media_type, media)


def _table_state_success(operation: dict[str, Any]) -> bool:
    for status, response in operation.get("responses", {}).items():
        if not str(status).startswith("2") or not isinstance(response, dict):
            continue
        schema = response.get("content", {}).get("application/json", {}).get("schema", {})
        if schema.get("$ref") == TABLE_STATE_REF:
            return True
    return False


def enrich_contract(spec: dict[str, Any]) -> dict[str, Any]:
    """Project middleware semantics into a FastAPI-derived OpenAPI document."""

    spec["servers"] = [LOCAL_SERVER]
    license_info = spec.get("info", {}).get("license")
    if isinstance(license_info, dict) and not ({"identifier", "url"} & set(license_info)):
        spec["info"]["x-license-note"] = license_info.get("name", "Licença não declarada")
        del spec["info"]["license"]

    components = spec.setdefault("components", {})
    schemas = components.setdefault("schemas", {})
    for schema in schemas.values():
        normalize_schema_examples(schema)
    schemas["HttpError"] = {
        "additionalProperties": False,
        "description": "Erro HTTP simples emitido pelo backend.",
        "properties": {"detail": {"description": "Mensagem segura e acionável.", "type": "string"}},
        "required": ["detail"],
        "title": "HttpError",
        "type": "object",
    }
    components.setdefault("securitySchemes", {}).update(
        {
            "PokerToken": {
                "description": (
                    "Token local opcional. O servidor exige este cabeçalho somente quando "
                    "`POKER_API_TOKEN` está configurado."
                ),
                "in": "header",
                "name": "X-Poker-Token",
                "type": "apiKey",
            },
            "PokerBearer": {
                "bearerFormat": "opaque",
                "description": "Alternativa ao cabeçalho `X-Poker-Token`.",
                "scheme": "bearer",
                "type": "http",
            },
        }
    )
    components.setdefault("headers", {}).update(
        {
            "CacheControl": {
                "description": "Política anti-cache aplicada a todas as respostas.",
                "schema": {"example": "no-store", "type": "string"},
            },
            "ContentSecurityPolicy": {
                "description": "Política CSP local aplicada pelo middleware de segurança.",
                "schema": {
                    "example": (
                        "default-src 'self'; img-src 'self' data:; "
                        "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
                        "connect-src 'self' ws: wss:"
                    ),
                    "type": "string",
                },
            },
            "ContentTypeOptions": {
                "description": "Impede MIME sniffing no navegador.",
                "schema": {"example": "nosniff", "type": "string"},
            },
            "ETag": {
                "description": "Versão atual da sessão entre aspas; reutilize em `If-Match`.",
                "schema": {"example": '"3"', "type": "string"},
            },
            "IdempotentReplay": {
                "description": "`true` quando a resposta veio do cache de idempotência.",
                "schema": {"type": "boolean"},
            },
            "RequestId": {
                "description": "Identificador de correlação aceito ou gerado pelo servidor.",
                "schema": {"type": "string"},
            },
            "ReferrerPolicy": {
                "description": "Bloqueia o envio do cabeçalho Referer.",
                "schema": {"example": "no-referrer", "type": "string"},
            },
            "SessionVersion": {
                "description": "Versão inteira não negativa da sessão.",
                "schema": {"minimum": 0, "type": "integer"},
            },
            "FrameOptions": {
                "description": "Impede incorporação da aplicação em frames.",
                "schema": {"example": "DENY", "type": "string"},
            },
        }
    )
    components.setdefault("parameters", {}).update(
        {
            "RequestId": {
                "description": "ID opcional de correlação (1 a 128 caracteres seguros).",
                "in": "header",
                "name": "X-Request-ID",
                "required": False,
                "schema": {
                    "maxLength": 128,
                    "minLength": 1,
                    "pattern": "^[A-Za-z0-9._-]+$",
                    "type": "string",
                },
            }
        }
    )

    for method, path, operation in operation_rows(spec):
        operation.setdefault(
            "description", operation.get("summary") or f"Operação {method} {path}."
        )
        parameters = operation.setdefault("parameters", [])
        if method == "POST" and path == "/tables":
            parameters[:] = [
                item
                for item in parameters
                if not (item.get("in") == "header" and item.get("name") == "If-Match")
            ]
        if {"$ref": "#/components/parameters/RequestId"} not in parameters:
            parameters.append({"$ref": "#/components/parameters/RequestId"})

        protected = path not in PUBLIC_PATHS
        operation["security"] = (
            [{"PokerToken": []}, {"PokerBearer": []}]
            if path == REMOTE_VLM_CONSENT_PATH
            else [{}, {"PokerToken": []}, {"PokerBearer": []}]
            if protected
            else []
        )
        if path == REMOTE_VLM_CONSENT_PATH:
            suffix = " Requires a configured 32-512 character printable-ASCII API token."
            if suffix not in operation["description"]:
                operation["description"] = operation["description"].rstrip() + suffix

        responses = operation.setdefault("responses", {})
        if protected:
            responses.setdefault("401", {"description": ERROR_DESCRIPTIONS["401"]})
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            responses.setdefault("403", {"description": ERROR_DESCRIPTIONS["403"]})
        if path == REMOTE_VLM_CONSENT_PATH:
            responses.setdefault("503", {"description": ERROR_DESCRIPTIONS["503"]})
        if path == "/ready":
            degraded = responses.setdefault(
                "503", {"description": "VLM remoto habilitado, mas incompleto."}
            )
            ready_content = responses.get("200", {}).get("content")
            if ready_content and "content" not in degraded:
                # JSON-compatible OpenAPI content; copying avoids aliasing responses.
                import copy

                degraded["content"] = copy.deepcopy(ready_content)

        has_route_bad_request = "400" in responses
        bad_request = responses.setdefault(
            "400", {"description": "Cabeçalho Host rejeitado pela política local."}
        )
        if has_route_bad_request:
            _merge_content(bad_request, _error_content())
            bad_request["description"] = (
                bad_request.get("description", "Requisição inválida.").rstrip(". ")
                + ". Um cabeçalho Host fora da allowlist também retorna texto simples."
            )
        _merge_content(bad_request, _host_error_content())

        has_idempotency = any(
            item.get("in") == "header" and item.get("name") == "Idempotency-Key"
            for item in parameters
            if isinstance(item, dict) and "$ref" not in item
        )
        if has_idempotency:
            responses.setdefault("409", {"description": ERROR_DESCRIPTIONS["409"]})
        if method == "POST" and path == "/copilot/from-image":
            responses.setdefault("413", {"description": ERROR_DESCRIPTIONS["413"]})
            responses.setdefault("415", {"description": ERROR_DESCRIPTIONS["415"]})

        table_state = _table_state_success(operation)
        for status, response in responses.items():
            if not isinstance(response, dict):
                continue
            response_headers = response.setdefault("headers", {})
            response_headers["X-Request-ID"] = {"$ref": "#/components/headers/RequestId"}
            for header_name, component_name in SECURITY_RESPONSE_HEADERS.items():
                response_headers[header_name] = {"$ref": f"#/components/headers/{component_name}"}
            is_documented_error = (
                str(status).startswith("4")
                and status != "422"
                and (status != "400" or has_route_bad_request)
            ) or (str(status).startswith("5") and path != "/ready")
            if is_documented_error:
                _merge_content(response, _error_content())
            if table_state and str(status).startswith("2"):
                response_headers.update(
                    {
                        "ETag": {"$ref": "#/components/headers/ETag"},
                        "X-Idempotent-Replay": {"$ref": "#/components/headers/IdempotentReplay"},
                        "X-Session-Version": {"$ref": "#/components/headers/SessionVersion"},
                    }
                )
    return spec
