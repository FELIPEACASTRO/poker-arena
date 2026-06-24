"""MLBot — nível 🔴 Expert por IA treinada (política neural via ONNX).

Carrega a política exportada do treino (notebook 05: warm-start no solver +
self-play) e joga implementando o protocolo `Bot`. O fluxo é a ACL ao contrário:
`encode(obs)` → ONNX → logits das 5 ações → aplica a máscara legal → escolhe a
melhor ação LEGAL → `to_action` devolve uma `Action` válida do motor.

onnxruntime/numpy entram só aqui (import dentro do __init__): o resto do backend
não depende deles a menos que o Expert seja usado.
"""

from __future__ import annotations

from pathlib import Path

from ..engine.actions import Action, ActionType
from ..ml.encoder import N_ACTIONS, encode, legal_mask, to_action
from .observation import Observation


def _choose(logits: list[float], obs: Observation) -> Action:
    """Escolhe a melhor ação LEGAL segundo os logits (puro/testável)."""
    mask = legal_mask(obs)
    best: int | None = None
    for i in range(N_ACTIONS):
        if mask[i] and (best is None or logits[i] > logits[best]):
            best = i
    if best is None:  # nenhuma das 5 ações é legal (não deve ocorrer) — desiste
        return Action(ActionType.FOLD)
    return to_action(obs, best)


class MLBot:
    def __init__(self, model_path: str | Path, name: str = "Rex (Expert)"):
        import numpy as np
        import onnxruntime as ort

        self.name = name
        self._np = np
        self._session = ort.InferenceSession(
            str(model_path), providers=["CPUExecutionProvider"]
        )
        self._input = self._session.get_inputs()[0].name

    def act(self, obs: Observation) -> Action:
        feats = self._np.asarray([encode(obs)], dtype=self._np.float32)
        logits = self._session.run(None, {self._input: feats})[0][0].tolist()
        return _choose(logits, obs)
