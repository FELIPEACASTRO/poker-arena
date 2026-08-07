"""Fail-closed offline preflight for the local master's-defense demonstration."""

from __future__ import annotations

import io
import json
import os
import time
import warnings
from pathlib import Path
from typing import Any

from poker_arena.api.app import create_app
from poker_arena.vision.synth import CANONICAL, render_table
from scripts.scan_secrets import scan
from scripts.validate_distribution import validate_distribution

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = PROJECT_ROOT.parent
DEMO_SEED = 2
MAX_WARM_REQUEST_SECONDS = 4.0


class DemoPreflightError(RuntimeError):
    """The local defense demonstration cannot be reproduced safely."""


def _require_local_offline_profile() -> None:
    forbidden_when_present = ("POKER_API_TOKEN", "POKER_VLM_URL", "POKER_VLM_API_KEY")
    present = [name for name in forbidden_when_present if os.environ.get(name)]
    if os.environ.get("POKER_ENABLE_REMOTE_VLM", "0") == "1":
        present.append("POKER_ENABLE_REMOTE_VLM")
    if present:
        raise DemoPreflightError(
            "perfil de banca deve ser local, anônimo e sem VLM remoto; variáveis incompatíveis: "
            + ", ".join(sorted(set(present)))
        )


def _require_local_dependencies() -> None:
    required = (
        PROJECT_ROOT / "backend" / ".venv" / "Scripts" / "python.exe",
        PROJECT_ROOT / "frontend" / "node_modules" / "vite" / "bin" / "vite.js",
        PROJECT_ROOT / "frontend" / "dist" / "index.html",
        PROJECT_ROOT / "api-docs" / "openapi.json",
        PROJECT_ROOT / "docs" / "GUIA_DE_NAVEGACAO_POKER_ARENA.pdf",
    )
    missing = [path.relative_to(PROJECT_ROOT).as_posix() for path in required if not path.is_file()]
    if missing:
        raise DemoPreflightError(f"dependências/artefatos locais ausentes: {missing}")


def _exercise_real_image_route() -> dict[str, Any]:
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"Using `httpx` with `starlette\.testclient` is deprecated.*",
        )
        from fastapi.testclient import TestClient

    image, truth = render_table(
        seed=DEMO_SEED,
        style=CANONICAL,
        n_board=5,
        noise=0.0,
        with_seats=True,
    )
    payload = io.BytesIO()
    image.save(payload, format="PNG")
    client = TestClient(create_app())

    def request() -> tuple[dict[str, Any], float]:
        started = time.perf_counter()
        response = client.post(
            "/copilot/from-image",
            files={"image": ("banca-sintetica.png", payload.getvalue(), "image/png")},
            data={"strict": "true", "my_stack": "1000"},
        )
        elapsed = time.perf_counter() - started
        if response.status_code != 200:
            raise DemoPreflightError(f"rota visual retornou HTTP {response.status_code}")
        body = response.json()
        if not isinstance(body, dict):
            raise DemoPreflightError("rota visual retornou payload inválido")
        return body, elapsed

    request()  # cold start is reported by the complete validator, not used as warm latency.
    body, warm_seconds = request()
    detected = body.get("detected")
    sanity = body.get("sanity")
    if not isinstance(detected, dict) or not isinstance(sanity, dict):
        raise DemoPreflightError("diagnóstico visual incompleto")
    exact = (
        detected.get("hole") == truth["hole"]
        and detected.get("board") == truth["board"]
        and detected.get("pot") == truth["pot"]
        and detected.get("n_players") == truth["n_players"]
        and detected.get("position") == truth["position"]
    )
    baseline_blocked = (
        body.get("engine") == "F1-template"
        and body.get("decision") is None
        and sanity.get("ok") is False
        and any("baseline F1" in problem for problem in sanity.get("problems", []))
    )
    if not exact:
        raise DemoPreflightError("fixture canônica da banca não foi reconhecida exatamente")
    if not baseline_blocked:
        raise DemoPreflightError("baseline F1 ultrapassou ou não explicou o gate científico")
    if warm_seconds > MAX_WARM_REQUEST_SECONDS:
        raise DemoPreflightError("latência quente da fixture excedeu quatro segundos")
    return {
        "fixture": f"synthetic-canonical-seed-{DEMO_SEED}",
        "engine": body["engine"],
        "exact_state": True,
        "decision_blocked": True,
        "warm_latency_ms": round(warm_seconds * 1_000, 1),
    }


def run_preflight() -> dict[str, Any]:
    _require_local_offline_profile()
    _require_local_dependencies()
    validate_distribution(PROJECT_ROOT, WORKSPACE_ROOT, require_clean=True)
    findings = scan(WORKSPACE_ROOT)
    if findings:
        raise DemoPreflightError(f"scanner de segredos bloqueou a banca: {len(findings)} achado(s)")
    vision = _exercise_real_image_route()
    return {
        "status": "READY_FOR_LOCAL_DEFENSE",
        "network_required": False,
        "remote_vlm_enabled": False,
        "git_clean": True,
        "secret_findings": 0,
        "vision": vision,
    }


def main() -> int:
    try:
        result = run_preflight()
    except (DemoPreflightError, OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"status": "NOT_READY", "reason": str(exc)}, ensure_ascii=True))
        return 1
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
