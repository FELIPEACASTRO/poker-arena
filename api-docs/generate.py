"""Gera a documentação da API a partir do app FastAPI (fonte única da verdade).

Produz, no diretório api-docs/:
  - openapi.json  : a especificação OpenAPI 3.1 (Swagger) já enriquecida.
  - insomnia.json : um projeto Insomnia (export v4) com TODOS os serviços,
                    organizados em pastas, com exemplos e um ambiente pronto.

Rode com o ambiente do backend:
    cd backend && uv run python ../api-docs/generate.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "backend"))

from poker_arena.api.app import app  # noqa: E402

# ---------------------------------------------------------------- OpenAPI
spec = app.openapi()
(HERE / "openapi.json").write_text(
    json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8"
)

# ---------------------------------------------------------------- Insomnia
WRK = "wrk_poker_arena"
ENV = "env_poker_base"
now = int(time.time() * 1000)
resources: list[dict] = [
    {
        "_id": WRK,
        "_type": "workspace",
        "name": "Poker Arena API",
        "description": (
            "Todos os serviços do Poker Arena. Fluxo: 1) 'Criar mesa' -> copie o "
            "table_id da resposta para o ambiente; 2) use as demais chamadas. "
            "O ambiente 'Base local' aponta para http://127.0.0.1:8000."
        ),
        "scope": "collection",
    },
    {
        "_id": ENV,
        "_type": "environment",
        "parentId": WRK,
        "name": "Base local",
        "data": {
            "base_url": "http://127.0.0.1:8000",
            "ws_url": "ws://127.0.0.1:8000",
            "table_id": "COLE_AQUI_O_table_id",
            "game_id": "COLE_AQUI_O_id_DA_PARTIDA",
            "seat": 0,
        },
        "metaSortKey": now,
    },
]

_sort = [0]


def folder(fid: str, name: str, desc: str) -> str:
    _sort[0] += 1
    resources.append(
        {
            "_id": fid,
            "_type": "request_group",
            "parentId": WRK,
            "name": name,
            "description": desc,
            "metaSortKey": _sort[0] * 1000,
        }
    )
    return fid


def req(parent, rid, name, method, path, desc, body=None):
    _sort[0] += 1
    r = {
        "_id": rid,
        "_type": "request",
        "parentId": parent,
        "name": name,
        "description": desc,
        "method": method,
        "url": "{{ _.base_url }}" + path,
        "headers": [],
        "metaSortKey": _sort[0] * 1000,
    }
    if body is not None:
        r["headers"].append({"name": "Content-Type", "value": "application/json"})
        r["body"] = {
            "mimeType": "application/json",
            "text": json.dumps(body, ensure_ascii=False, indent=2),
        }
    resources.append(r)


# --- Mesa ---
f = folder("fld_mesa", "Mesa", "Criar uma partida e ler o estado da mesa.")
req(
    f, "req_criar", "Criar mesa (você joga)", "POST", "/tables",
    "Cria a partida. COPIE o `table_id` da resposta para o ambiente (variavel table_id).",
    {
        "human_name": "VOCE",
        "bots": [
            {"name": "Luna", "level": "random"},
            {"name": "Caio", "level": "heuristic"},
            {"name": "Sofia", "level": "montecarlo"},
        ],
        "starting_stack": 1000,
        "small_blind": 10,
        "big_blind": 20,
        "rebuy": True,
        "mode": "play",
        "hand_limit": None,
        "seed": None,
    },
)
req(
    f, "req_criar_watch", "Criar mesa (Modo Laboratorio)", "POST", "/tables",
    "Cria uma partida so de bots (modo watch). Avance com 'Avancar bot (step)'.",
    {
        "bots": [
            {"name": "Luna", "level": "random"},
            {"name": "Caio", "level": "heuristic"},
            {"name": "Sofia", "level": "montecarlo"},
            {"name": "Rex", "level": "adaptive"},
        ],
        "starting_stack": 1500,
        "small_blind": 10,
        "big_blind": 20,
        "rebuy": False,
        "mode": "watch",
        "hand_limit": 50,
        "seed": 42,
    },
)
req(
    f, "req_estado", "Ler estado da mesa", "GET", "/tables/{{ _.table_id }}",
    "Estado completo e atual da mesa (sem alterar nada). Olhe o campo `phase`.",
)

# --- Jogada ---
f = folder("fld_jogada", "Jogada", "Avancar o jogo: sua jogada, jogada dos bots e proxima mao.")
req(
    f, "req_pagar", "Pagar (call)", "POST", "/tables/{{ _.table_id }}/actions",
    "Sua jogada no turno do humano. So vale o que estiver em legal.actions.",
    {"type": "call", "amount": 0},
)
req(
    f, "req_passar", "Passar (check)", "POST", "/tables/{{ _.table_id }}/actions",
    "Passar quando nao ha aposta a pagar.",
    {"type": "check", "amount": 0},
)
req(
    f, "req_aumentar", "Aumentar (raise para 80)", "POST", "/tables/{{ _.table_id }}/actions",
    "amount = valor TOTAL da aposta (entre legal.min_raise_to e legal.max_raise_to).",
    {"type": "raise", "amount": 80},
)
req(
    f, "req_allin", "All-in", "POST", "/tables/{{ _.table_id }}/actions",
    "Ir com todas as fichas.",
    {"type": "all_in", "amount": 0},
)
req(
    f, "req_desistir", "Desistir (fold)", "POST", "/tables/{{ _.table_id }}/actions",
    "Abrir mao da mao atual.",
    {"type": "fold", "amount": 0},
)
req(
    f, "req_step", "Avancar bot (step)", "POST", "/tables/{{ _.table_id }}/step",
    "Modo watch: avanca UMA jogada de bot. Valido so em phase == bot_turn.",
)
req(
    f, "req_next", "Proxima mao", "POST", "/tables/{{ _.table_id }}/next-hand",
    "Distribui a proxima mao. Valido so em phase == hand_over.",
)

# --- Jogadores ---
f = folder("fld_jogadores", "Jogadores", "Entrar/sair de jogadores na mesa ao vivo.")
req(
    f, "req_addbot", "Adicionar bot", "POST", "/tables/{{ _.table_id }}/players",
    "Senta um novo bot do nivel escolhido (vale a partir da proxima mao). Mesa 6-max.",
    {"level": "montecarlo", "name": "Ana", "buy_in": None},
)
req(
    f, "req_rmplayer", "Remover jogador (cadeira {{ _.seat }})", "DELETE",
    "/tables/{{ _.table_id }}/players/{{ _.seat }}",
    "Remove o jogador da cadeira (indice em roster). Nao remove o humano; minimo 2 jogadores.",
)

# --- Catalogo ---
f = folder("fld_catalogo", "Catalogo", "Dados de apoio.")
req(f, "req_levels", "Niveis de IA", "GET", "/levels", "Lista os niveis de bot disponiveis.")

# --- Auditoria ---
f = folder("fld_auditoria", "Auditoria", "Historico das partidas e replay.")
req(f, "req_games", "Listar partidas", "GET", "/games", "Resumo de todas as partidas gravadas.")
req(
    f, "req_game", "Replay de partida", "GET", "/games/{{ _.game_id }}",
    "Log completo de uma partida (cole um id de /games no ambiente game_id).",
)

# --- Sistema ---
f = folder("fld_sistema", "Sistema", "Saude do servico.")
req(f, "req_health", "Health", "GET", "/health", "Retorna {status: ok} se a API esta no ar.")

# --- Tempo real (WebSocket) ---
f = folder("fld_ws", "Tempo real", "Canal WebSocket para jogar com push de estado.")
_sort[0] += 1
resources.append(
    {
        "_id": "req_ws",
        "_type": "websocket_request",
        "parentId": f,
        "name": "WebSocket da mesa",
        "url": "{{ _.ws_url }}/tables/{{ _.table_id }}/ws",
        "description": (
            "Conecte e receba o estado inicial; envie {\"type\":\"call\"} (ou raise com "
            "amount) para jogar e receber o novo estado por push."
        ),
        "headers": [],
        "metaSortKey": _sort[0] * 1000,
    }
)

insomnia = {
    "_type": "export",
    "__export_format": 4,
    "__export_date": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
    "__export_source": "poker-arena:generate.py",
    "resources": resources,
}
(HERE / "insomnia.json").write_text(
    json.dumps(insomnia, ensure_ascii=False, indent=2), encoding="utf-8"
)

# ---------------------------------------------------------------- Swagger HTML
# Swagger UI com a spec EMBUTIDA -> abre por duplo-clique, sem servidor nem CORS.
swagger_html = """<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Poker Arena API — Swagger</title>
  <link rel="icon" href="../assets/poker.png">
  <link rel="stylesheet" href="./vendor/swagger-ui.css">
  <style>
    body { margin: 0; background: #0d1117; }
    .topbanner { font-family: system-ui, sans-serif; color: #e6edf3; background:
      linear-gradient(90deg,#0b3b2a,#0d1117); padding: 14px 20px; font-size: 14px;
      border-bottom: 2px solid #c39a55; }
    .topbanner b { color: #34d399; }
    .swagger-ui .topbar { display: none; }
  </style>
</head>
<body>
  <div class="topbanner">♠ <b>Poker Arena API</b> — documentação interativa (Swagger).
    Para o "Try it out" funcionar, deixe o backend rodando em http://127.0.0.1:8000.</div>
  <div id="swagger"></div>
  <script src="./vendor/swagger-ui-bundle.js"></script>
  <script>
    const spec = __SPEC__;
    window.ui = SwaggerUIBundle({
      spec: spec,
      dom_id: "#swagger",
      deepLinking: true,
      docExpansion: "list",
      defaultModelsExpandDepth: 1,
      tryItOutEnabled: true,
      filter: true,
    });
  </script>
</body>
</html>
"""
swagger_html = swagger_html.replace("__SPEC__", json.dumps(spec, ensure_ascii=False))
(HERE / "swagger.html").write_text(swagger_html, encoding="utf-8")

print("OK")
print("  openapi.json :", len(spec["paths"]), "paths")
print("  insomnia.json:", sum(1 for r in resources if r["_type"] in ("request", "websocket_request")), "requests")
