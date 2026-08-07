"""Cobre o caminho de BOOT (lifespan + warmup) — que o fixture padrão NÃO exercita.

A auditoria adversarial apontou: `TestClient(app)` sem `with` não dispara o lifespan do
Starlette, então os 245 testes nunca cobriam o warmup no boot. Aqui subimos o app COM o
`with` (dispara startup/shutdown) e provamos: (a) desligado por POKER_WARMUP=0 o app sobe e
responde; (b) ligado, o thread daemon de aquecimento é iniciado e o boot NÃO quebra por
causa dele; (c) o warmup é best-effort (falha no load não derruba o servidor).
"""

from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from poker_arena.api import app as app_module
from poker_arena.api.app import create_app


def test_boot_com_warmup_desligado_sobe_e_responde(monkeypatch):
    monkeypatch.setenv("POKER_WARMUP", "0")
    with TestClient(create_app()) as c:  # `with` dispara o lifespan (startup + shutdown)
        assert c.get("/health").json() == {"status": "ok"}


def test_boot_rejeita_flag_de_warmup_ambigua(monkeypatch):
    monkeypatch.setenv("POKER_WARMUP", "talvez")
    with (
        pytest.raises(RuntimeError, match="POKER_WARMUP deve ser 0 ou 1"),
        TestClient(create_app()),
    ):
        pass


def test_boot_ligado_dispara_o_thread_de_warmup_sem_quebrar(monkeypatch):
    # não deixamos o warmup REAL rodar (lento/carrega modelo): trocamos por um espião que
    # só sinaliza que foi chamado no thread daemon — provamos que o boot o dispara.
    called = threading.Event()
    monkeypatch.setenv("POKER_WARMUP", "1")
    monkeypatch.setattr(app_module, "_warmup_vision", called.set)
    with TestClient(create_app()) as c:
        assert c.get("/health").status_code == 200
    assert called.wait(timeout=5.0), "o lifespan deveria ter disparado o warmup no boot"


def test_warmup_vision_nunca_propaga_excecao_e_registra_falha(monkeypatch, caplog):
    # _warmup_vision engole qualquer erro interno (não pode derrubar o servidor). Ele importa
    # os reconhecedores do pacote ..vision a cada chamada, então mockamos ambos ali.
    import poker_arena.vision as vision_pkg

    def _explode(*_a, **_k):
        raise RuntimeError("onnx inválido")

    monkeypatch.setattr(vision_pkg, "recognize_table_onnx", _explode)
    monkeypatch.setattr(vision_pkg, "recognize_table", _explode)
    app_module._warmup_vision()  # não deve levantar
    assert "Optional vision warmup failed" in caplog.text
