"""Demo ao vivo: sobe o servidor real (uvicorn) e joga uma partida via HTTP.

Roda com:  uv run python scripts/demo_play.py
Logs no estilo 'Use a Cabeca' (ver ml/LOGGING_STYLE.md).
"""

from __future__ import annotations

import threading
import time

import httpx
import uvicorn

BASE = "http://127.0.0.1:8000"


def box(titulo: str, linhas: list[str]) -> None:
    largura = max([len(titulo)] + [len(s) for s in linhas])
    print("  +" + "-" * (largura + 2) + "+")
    print("  | " + titulo.ljust(largura) + " |")
    print("  +" + "-" * (largura + 2) + "+")
    for s in linhas:
        print("  | " + s.ljust(largura) + " |")
    print("  +" + "-" * (largura + 2) + "+")


def start_server() -> None:
    cfg = uvicorn.Config(
        "poker_arena.api.app:app", host="127.0.0.1", port=8000, log_level="warning"
    )
    threading.Thread(target=uvicorn.Server(cfg).run, daemon=True).start()


def wait_health(client: httpx.Client, tries: int = 40) -> bool:
    for _ in range(tries):
        try:
            if client.get(BASE + "/health").status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    return False


def show(st: dict) -> None:
    board = " ".join(st["board"]) or "(sem cartas comunitarias ainda)"
    linhas = [
        f"Mao #{st['hand_number']}  |  fase: {st['phase']}  |  pote: {st['pot']}",
        f"Mesa: {board}",
    ]
    for s in st["seats"]:
        seta = "<<<" if s["is_turn"] else "   "
        btn = "(D)" if s["is_button"] else "   "
        cartas = " ".join(s["cards"]) if s["cards"] else "?? ??"
        linhas.append(
            f"{seta} {s['name']:<5} {btn} {s['kind']:<14} fichas={s['stack']:<4} {cartas}"
        )
    box("ESTADO DA MESA", linhas)


def pick(legal: dict) -> dict:
    acts = legal["actions"]
    if "check" in acts:
        return {"type": "check"}
    if "call" in acts and legal["to_call"] <= 60:
        return {"type": "call"}
    return {"type": "fold"}


def main() -> None:
    start_server()
    with httpx.Client(timeout=10) as client:
        box("POKER ARENA - DEMO AO VIVO (via API HTTP)", [
            "Subo o servidor de verdade, crio uma mesa, jogo contra 5 bots",
            "e te mostro a partida ponta a ponta - tudo pela API REST.",
        ])
        if not wait_health(client):
            print("  Servidor nao subiu. Abortei.")
            return
        body = {
            "bots": [
                {"name": n, "level": lvl}
                for n, lvl in [
                    ("Luna", "random"), ("Caio", "heuristic"), ("Sofia", "heuristic"),
                    ("Alex", "montecarlo"), ("Maya", "montecarlo"),
                ]
            ],
            "starting_stack": 500,
            "seed": 42,
        }
        st = client.post(BASE + "/tables", json=body).json()
        tid = st["table_id"]
        print(f"\n  Mesa criada: {tid}\n")
        hands = 0
        for _ in range(60):
            show(st)
            if st["phase"] == "human_turn":
                act = pick(st["legal"])
                print(f"  VOCE (demo) -> {act['type'].upper()}\n")
                st = client.post(f"{BASE}/tables/{tid}/actions", json=act).json()
            elif st["phase"] == "hand_over":
                won = ", ".join(st["seats"][i]["name"] for i in (st["winners"] or []))
                box("FIM DA MAO", [f"Vencedor(es): {won}"])
                hands += 1
                if hands >= 3:
                    break
                st = client.post(f"{BASE}/tables/{tid}/next-hand").json()
            else:  # game_over
                won = ", ".join(st["seats"][i]["name"] for i in (st["winners"] or []))
                box("FIM DE JOGO", [f"Ultimo vencedor: {won}"])
                break
        box("DEMO CONCLUIDA", [
            "A API jogou a partida inteira ponta a ponta.",
            "E a MESMA API que o frontend React vai consumir.",
        ])


if __name__ == "__main__":
    main()
