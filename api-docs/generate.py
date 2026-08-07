"""Generate deterministic OpenAPI, Insomnia and offline Swagger artifacts."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import stat
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
VENDOR_DIR = HERE / "vendor"
SWAGGER_UI_VERSION = "5.17.14"
VENDOR_RECEIPT_SCHEMA = "poker-arena-vendored-asset-receipt-v1"
VENDORED_SWAGGER_FILES: dict[str, tuple[int, str, str | None]] = {
    "LICENSE": (
        11358,
        "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
        "package/LICENSE",
    ),
    "NOTICE": (
        55,
        "0d20d1adef18aee3f40dd258172155521ce702ac445cb5f7b7d60ed32dad2fb2",
        "package/NOTICE",
    ),
    "swagger-ui-bundle.js": (
        1452753,
        "c2e4a9ef08144839ff47c14202063ecfe4e59e70a4e7154a26bd50d880c88ba1",
        "package/swagger-ui-bundle.js",
    ),
    "swagger-ui-bundle.js.LICENSE.txt": (
        298,
        "314861a55a8edcac71b2c486ab627fa8a0e108c8dd1a766c807668fefd800fb4",
        None,
    ),
    "swagger-ui.css": (
        152071,
        "40170f0ee859d17f92131ba707329a88a070e4f66874d11365e9a77d232f6117",
        "package/swagger-ui.css",
    ),
}
sys.path.insert(0, str(ROOT / "backend"))

from poker_arena.api.app import app  # noqa: E402
from poker_arena.api.openapi_contract import (  # noqa: E402
    HTTP_METHODS,
    LOCAL_SERVER,
    PUBLIC_PATHS,
    REMOTE_VLM_CONSENT_PATH,
)
from poker_arena.api.openapi_contract import (  # noqa: E402
    enrich_contract as _enrich_contract,
)
from poker_arena.api.openapi_contract import (  # noqa: E402
    normalize_schema_examples as _normalize_schema_examples,
)
from poker_arena.api.openapi_contract import (  # noqa: E402
    operation_rows as _operation_rows,
)

__all__ = [
    "HTTP_METHODS",
    "LOCAL_SERVER",
    "PUBLIC_PATHS",
    "REMOTE_VLM_CONSENT_PATH",
    "_enrich_contract",
    "_normalize_schema_examples",
    "_validate_vendor_assets",
]

WORKSPACE_ID = "wrk_poker_arena"
ENVIRONMENT_ID = "env_poker_base"
PATH_PARAMETER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _is_reparse_or_link(path: Path) -> bool:
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return path.is_symlink() or bool(attributes & reparse_flag)


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"chave JSON duplicada no receipt Swagger: {key}")
        result[key] = value
    return result


def _validate_vendor_assets(vendor_dir: Path = VENDOR_DIR) -> None:
    """Fail closed if vendored Swagger assets diverge from the pinned receipt."""

    try:
        if _is_reparse_or_link(vendor_dir) or not vendor_dir.is_dir():
            raise ValueError("diretorio vendor Swagger nao e um diretorio regular")
        receipt_path = vendor_dir / "receipt.json"
        if _is_reparse_or_link(receipt_path) or not receipt_path.is_file():
            raise ValueError("receipt Swagger ausente, reparse ou nao regular")
        if receipt_path.stat().st_size > 32 * 1024:
            raise ValueError("receipt Swagger excede o limite de 32 KiB")
        receipt = json.loads(
            receipt_path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("receipt Swagger ilegivel ou invalido") from exc

    if (
        not isinstance(receipt, dict)
        or set(receipt) != {"schema", "component", "origin", "files"}
        or receipt.get("schema") != VENDOR_RECEIPT_SCHEMA
    ):
        raise ValueError("schema do receipt Swagger nao reconhecido")
    component = receipt.get("component")
    if component != {
        "license": "Apache-2.0",
        "name": "Swagger UI",
        "package": "swagger-ui-dist",
        "source_repository": "https://github.com/swagger-api/swagger-ui",
        "version": SWAGGER_UI_VERSION,
    }:
        raise ValueError("metadados do componente Swagger divergentes")
    origin = receipt.get("origin")
    if origin != {
        "npm_integrity_sha512": (
            "sha512-CVbSfaLpstV65OnSjbXfVd6Sta3q3F7Cj/yYuvHMp1P90LztOLs6PfUnKE"
            "VAeiIVQt9u2SaPwv0LiH/OyMjHRw=="
        ),
        "npm_shasum_sha1": "e2c222e5bf9e15ccf80ec4bc08b4aaac09792fd6",
        "registry": "https://registry.npmjs.org/",
        "release_tag": "v5.17.14",
        "retrieved_on": "2026-07-18",
        "tarball": (
            "https://registry.npmjs.org/swagger-ui-dist/-/swagger-ui-dist-5.17.14.tgz"
        ),
        "tarball_sha256": (
            "c57badf459aa6e65cc036b3862d0502a63f9a22546407ffcb0e64f85f816bb28"
        ),
    }:
        raise ValueError("origem ou integridade do tarball Swagger divergente")

    entries = receipt.get("files")
    if not isinstance(entries, list):
        raise ValueError("lista de arquivos Swagger ausente no receipt")
    by_path: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "bytes",
            "path",
            "sha256",
            "upstream_path",
        }:
            raise ValueError("entrada de arquivo Swagger possui schema invalido")
        path_name = entry.get("path")
        if not isinstance(path_name, str) or path_name in by_path:
            raise ValueError("path Swagger duplicado ou invalido no receipt")
        by_path[path_name] = entry
    if set(by_path) != set(VENDORED_SWAGGER_FILES):
        raise ValueError("inventario Swagger diverge do conjunto fixado")

    resolved_vendor = vendor_dir.resolve(strict=True)
    for name, (
        expected_bytes,
        expected_hash,
        upstream_path,
    ) in VENDORED_SWAGGER_FILES.items():
        entry = by_path[name]
        if (
            entry["bytes"] != expected_bytes
            or entry["sha256"] != expected_hash
            or entry["upstream_path"] != upstream_path
        ):
            raise ValueError(f"receipt Swagger diverge para {name}")
        path = vendor_dir / name
        try:
            if (
                _is_reparse_or_link(path)
                or not path.is_file()
                or path.resolve(strict=True).parent != resolved_vendor
            ):
                raise ValueError(f"asset Swagger nao regular: {name}")
            payload = path.read_bytes()
        except OSError as exc:
            raise ValueError(f"asset Swagger ilegivel: {name}") from exc
        if len(payload) != expected_bytes:
            raise ValueError(f"tamanho do asset Swagger diverge: {name}")
        if hashlib.sha256(payload).hexdigest() != expected_hash:
            raise ValueError(f"SHA-256 do asset Swagger diverge: {name}")


JSON_EXAMPLES: dict[tuple[str, str], dict[str, Any]] = {
    ("POST", "/tables"): {
        "human_name": "VOCE",
        "bots": [
            {"name": "Luna", "level": "random"},
            {"name": "Caio", "level": "heuristic"},
        ],
        "starting_stack": 1000,
        "small_blind": 10,
        "big_blind": 20,
        "rebuy": True,
        "mode": "play",
        "hand_limit": 50,
        "seed": 42,
    },
    ("POST", "/tables/{table_id}/actions"): {"type": "call", "amount": 0},
    ("POST", "/tables/{table_id}/players"): {
        "level": "montecarlo",
        "name": "Ana",
        "buy_in": 1000,
    },
    ("POST", "/copilot"): {
        "hole": ["As", "Ah"],
        "board": ["Kd", "7c", "2s"],
        "pot": 100,
        "to_call": 20,
        "my_stack": 1000,
        "effective_stack": 1000,
        "num_opponents": 1,
        "table_size": 2,
        "in_position": True,
        "position": "SB",
        "big_blind": 20,
        "hero_current_bet": 0,
        "current_bet": 20,
        "min_raise_increment": 20,
        "raise_reopened": True,
    },
    ("POST", "/copilot/review-hand"): {
        "phh": (
            "variant = 'NT'\n"
            "antes = [0, 0]\n"
            "blinds_or_straddles = [1, 2]\n"
            "min_bet = 2\n"
            "starting_stacks = [100, 100]\n"
            "players = ['Alice', 'Bob']\n"
            "actions = ['d dh p1 AsKd', 'd dh p2 QsQh', 'p2 cc', 'p1 cc', "
            "'d db 2c3d4h', 'p1 cc', 'p2 cc', 'd db 5s', 'p1 cc', 'p2 cc', "
            "'d db 6c', 'p1 cc', 'p2 cc']"
        ),
        "player": 1,
    },
    ("POST", "/copilot/remote-vlm/consent-sessions"): {"consent": True},
    ("DELETE", "/copilot/remote-vlm/consent-sessions"): {
        "session_id": "replace-with-issued-session-id",
    },
}


def _stable_id(kind: str, value: str) -> str:
    digest = hashlib.sha256(f"{kind}:{value}".encode()).hexdigest()[:16]
    return f"{kind}_{digest}"


def _insomnia_path(path: str) -> str:
    return re.sub(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", r"{{ _.\1 }}", path)


def _resolve_local_ref(spec: dict[str, Any], value: dict[str, Any]) -> dict[str, Any]:
    """Resolve a local JSON Pointer used by FastAPI's OpenAPI document."""
    current = value
    seen: set[str] = set()
    while isinstance(current, dict) and set(current) == {"$ref"}:
        ref = current["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/") or ref in seen:
            raise ValueError(f"referência OpenAPI local inválida: {ref!r}")
        seen.add(ref)
        target: Any = spec
        for raw_part in ref[2:].split("/"):
            part = raw_part.replace("~1", "/").replace("~0", "~")
            target = target[part]
        if not isinstance(target, dict):
            raise ValueError(f"referência OpenAPI não aponta para objeto: {ref}")
        current = target
    return current


def _parameter_value(parameter: dict[str, Any]) -> tuple[str, bool]:
    name = parameter["name"]
    values = {
        "Idempotency-Key": ("{{ _.idempotency_key }}", True),
        "If-Match": ("{{ _.expected_version }}", True),
        "X-Request-ID": ("{{ _.request_id }}", True),
    }
    if name in values:
        return values[name]
    schema = parameter.get("schema", {})
    default = schema.get("default", "")
    return str(default), not parameter.get("required", False)


def _multipart_parameters(
    spec: dict[str, Any], media: dict[str, Any]
) -> list[dict[str, Any]]:
    schema = _resolve_local_ref(spec, media.get("schema", {}))
    required = set(schema.get("required", []))
    params: list[dict[str, Any]] = []
    for name, raw_property in schema.get("properties", {}).items():
        prop = _resolve_local_ref(spec, raw_property)
        description = prop.get("description", "")
        if prop.get("contentMediaType") or prop.get("format") == "binary":
            item: dict[str, Any] = {"fileName": "", "name": name, "type": "file"}
        else:
            default = prop.get("default", "")
            value = (
                json.dumps(default).lower()
                if isinstance(default, bool)
                else str(default)
            )
            item = {"name": name, "value": value}
        if name not in required:
            item["disabled"] = True
        if description:
            item["description"] = description
        params.append(item)
    return params


def _build_insomnia(spec: dict[str, Any]) -> dict[str, Any]:
    rows = list(_operation_rows(spec))
    tag_docs = {
        item["name"]: item.get("description", "") for item in spec.get("tags", [])
    }
    tags = sorted(
        {(operation.get("tags") or ["Outros"])[0] for _, _, operation in rows}
    )
    path_variables = sorted(
        {name for _, path, _ in rows for name in PATH_PARAMETER.findall(path)}
    )
    environment: dict[str, Any] = {
        "api_token": "",
        "base_url": LOCAL_SERVER["url"],
        "expected_version": "0",
        "idempotency_key": "CHANGE-ME-UNIQUE-PER-COMMAND",
        "request_id": "",
        "ws_url": "ws://127.0.0.1:8000",
    }
    environment.update(
        {
            name: 0 if name == "seat" else f"COLE_AQUI_O_{name}"
            for name in path_variables
        }
    )
    resources: list[dict[str, Any]] = [
        {
            "_id": WORKSPACE_ID,
            "_type": "workspace",
            "name": "Poker Arena API",
            "description": (
                "Contrato completo gerado do FastAPI. Nenhuma credencial real é incluída; "
                "configure o ambiente local somente se POKER_API_TOKEN estiver ativo."
            ),
            "scope": "collection",
        },
        {
            "_id": ENVIRONMENT_ID,
            "_type": "environment",
            "parentId": WORKSPACE_ID,
            "name": "Base local",
            "metaSortKey": 0,
            "data": environment,
        },
    ]
    folders: dict[str, str] = {}
    for index, tag in enumerate(tags, 1):
        folders[tag] = _stable_id("fld", tag)
        resources.append(
            {
                "_id": folders[tag],
                "_type": "request_group",
                "parentId": WORKSPACE_ID,
                "name": tag,
                "description": tag_docs.get(tag, ""),
                "metaSortKey": index * 1000,
            }
        )

    for index, (method, path, operation) in enumerate(rows, 1):
        tag = (operation.get("tags") or ["Outros"])[0]
        headers: list[dict[str, Any]] = []
        security = operation.get("security") or []
        if security:
            authentication_required = {} not in security
            headers.extend(
                [
                    {
                        "description": (
                            "Obrigatório: token ASCII imprimível de 32 a 512 caracteres."
                            if authentication_required
                            else "Habilite se POKER_API_TOKEN estiver configurado."
                        ),
                        "disabled": not authentication_required,
                        "name": "X-Poker-Token",
                        "value": "{{ _.api_token }}",
                    },
                    {
                        "description": (
                            "Alternativa bearer: habilite este cabeçalho OU X-Poker-Token."
                        ),
                        "disabled": True,
                        "name": "Authorization",
                        "value": "Bearer {{ _.api_token }}",
                    },
                ]
            )
        for raw_parameter in operation.get("parameters", []):
            parameter = _resolve_local_ref(spec, raw_parameter)
            if parameter.get("in") != "header":
                continue
            value, disabled = _parameter_value(parameter)
            headers.append(
                {
                    "description": parameter.get("description", ""),
                    "disabled": disabled,
                    "name": parameter["name"],
                    "value": value,
                }
            )
        request: dict[str, Any] = {
            "_id": _stable_id("req", f"{method}:{path}"),
            "_type": "request",
            "parentId": folders[tag],
            "name": operation.get("summary") or f"{method} {path}",
            "description": operation.get("description", ""),
            "method": method,
            "url": "{{ _.base_url }}" + _insomnia_path(path),
            "headers": headers,
            "metaSortKey": index * 1000,
        }
        content = operation.get("requestBody", {}).get("content", {})
        if "application/json" in content:
            if (method, path) not in JSON_EXAMPLES:
                raise ValueError(
                    f"exemplo JSON obrigatório ausente para {method} {path}"
                )
            headers.insert(0, {"name": "Content-Type", "value": "application/json"})
            request["body"] = {
                "mimeType": "application/json",
                "text": json.dumps(
                    JSON_EXAMPLES[(method, path)],
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
            }
        elif "multipart/form-data" in content:
            request["body"] = {
                "mimeType": "multipart/form-data",
                "params": _multipart_parameters(spec, content["multipart/form-data"]),
            }
        resources.append(request)

    ws_parent = folders.get("Tempo real")
    if ws_parent is None:
        ws_parent = _stable_id("fld", "Tempo real")
        resources.append(
            {
                "_id": ws_parent,
                "_type": "request_group",
                "parentId": WORKSPACE_ID,
                "name": "Tempo real",
                "description": "Canal WebSocket com push de estado.",
                "metaSortKey": (len(tags) + 1) * 1000,
            }
        )
    resources.append(
        {
            "_id": _stable_id("ws", "/tables/{table_id}/ws"),
            "_type": "websocket_request",
            "parentId": ws_parent,
            "name": "WebSocket da mesa",
            "url": "{{ _.ws_url }}/tables/{{ _.table_id }}/ws",
            "description": (
                "Recebe um TableStateResponse inicial. Aceita mensagens objeto de até 4096 "
                "bytes com apenas type, amount, command_id e expected_version. Envie, por exemplo, "
                '`{"type":"call","command_id":"unique-1","expected_version":0}`. '
                "`command_id` (1..128 caracteres seguros) torna a mensagem idempotente e "
                "`expected_version` inteiro não negativo evita estado obsoleto. Erros retornam "
                "um objeto com `error` e, quando aplicável, `code`: validation_error, "
                "idempotency_conflict, version_conflict ou invalid_action. Antes do upgrade, "
                "o servidor pode fechar com 4401 (token), 4403 (Origin) ou 4404 (mesa)."
            ),
            "headers": [
                {
                    "name": "X-Poker-Token",
                    "value": "{{ _.api_token }}",
                    "disabled": True,
                }
            ],
            "metaSortKey": (len(rows) + 1) * 1000,
        }
    )
    return {
        "_type": "export",
        "__export_format": 4,
        "__export_date": "1970-01-01T00:00:00.000Z",
        "__export_source": "poker-arena:generate.py",
        "resources": resources,
    }


def _build_swagger(spec: dict[str, Any]) -> str:
    raw = json.dumps(spec, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    encoded = base64.b64encode(raw.encode("ascii")).decode("ascii")
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; img-src 'self' data:;
style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline';
connect-src http://127.0.0.1:8000 ws://127.0.0.1:8000">
<title>Poker Arena API - Swagger</title>
<link rel="stylesheet" href="./vendor/swagger-ui.css">
<style>body{{margin:0;background:#0d1117}}.topbanner{{font:14px system-ui;color:#e6edf3;
background:#0b3b2a;padding:14px 20px}}.swagger-ui .topbar{{display:none}}</style></head>
<body><div class="topbanner">Em file:// a documentacao e somente leitura. Para executar
chamadas, use http://127.0.0.1:8000/docs.</div><div id="swagger"></div>
<script src="./vendor/swagger-ui-bundle.js"></script><script>
const spec = JSON.parse(atob("{encoded}"));
const loopback = location.hostname === "localhost" || location.hostname === "127.0.0.1"
  || location.hostname === "[::1]";
const canCallApi = (location.protocol === "http:" || location.protocol === "https:") && loopback;
window.ui=SwaggerUIBundle({{spec,dom_id:"#swagger",deepLinking:true,filter:true,
persistAuthorization:false,tryItOutEnabled:canCallApi,supportedSubmitMethods:canCallApi
?["get","put","post","delete","options","head","patch"]:[]}});
</script></body></html>
"""


def build_artifacts() -> tuple[dict[str, Any], dict[str, Any], str]:
    """Build artifacts without writing or mutating FastAPI's cached schema."""
    _validate_vendor_assets()
    spec = json.loads(json.dumps(app.openapi(), ensure_ascii=False))
    return spec, _build_insomnia(spec), _build_swagger(spec)


def _artifact_payloads() -> dict[str, bytes]:
    spec, insomnia, swagger = build_artifacts()
    return {
        "openapi.json": (
            json.dumps(spec, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode(),
        "insomnia.json": (
            json.dumps(insomnia, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode(),
        "swagger.html": swagger.encode(),
    }


def write_artifacts(output_dir: Path = HERE) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in _artifact_payloads().items():
        (output_dir / name).write_bytes(payload)


def check_artifacts(output_dir: Path = HERE) -> tuple[str, ...]:
    """Return drifted/missing artifact names without changing the checkout."""

    mismatches: list[str] = []
    for name, expected in _artifact_payloads().items():
        path = output_dir / name
        try:
            current = path.read_bytes()
        except OSError:
            current = b""
        if current != expected:
            mismatches.append(name)
    return tuple(mismatches)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Detect drift without writing."
    )
    parser.add_argument("--output-dir", type=Path, default=HERE)
    args = parser.parse_args(argv)

    if args.check:
        mismatches = check_artifacts(args.output_dir)
        if mismatches:
            print("DRIFT: " + ", ".join(mismatches))
            return 1
        print("OK: committed API artifacts match the generator")
        return 0

    write_artifacts(args.output_dir)
    generated, insomnia, _ = build_artifacts()
    count = sum(
        resource["_type"] in {"request", "websocket_request"}
        for resource in insomnia["resources"]
    )
    print(f"OK: {len(generated['paths'])} paths; {count} requests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
