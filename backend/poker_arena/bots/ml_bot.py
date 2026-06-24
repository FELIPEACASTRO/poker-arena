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
from ..ml.encoder import ACTIONS, N_ACTIONS, encode, legal_mask, to_action
from .insight import BotInsight
from .observation import Observation

# rótulos curtos das 5 ações discretas (pro glass-box)
_PT = {
    "fold": "desistir",
    "check_call": "pagar",
    "raise_half": "aumentar ½",
    "raise_pot": "aumentar pote",
    "all_in": "all-in",
}


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
        self._last_insight: BotInsight | None = None

    def _softmax_legal(self, logits: list[float], obs: Observation) -> list[float]:
        """Distribuição da rede SÓ sobre as ações legais (ilegais ≈ 0)."""
        mask = legal_mask(obs)
        masked = self._np.array(
            [logits[i] if mask[i] else -self._np.inf for i in range(N_ACTIONS)],
            dtype="float64",
        )
        masked -= masked.max()
        exps = self._np.exp(masked)  # exp(-inf) = 0
        return (exps / exps.sum()).tolist()

    def act(self, obs: Observation) -> Action:
        feats = self._np.asarray([encode(obs)], dtype=self._np.float32)
        logits = self._session.run(None, {self._input: feats})[0][0].tolist()
        probs = self._softmax_legal(logits, obs)
        top = max(range(N_ACTIONS), key=lambda i: probs[i])
        self._last_insight = BotInsight(
            kind="expert",
            label=f"Rede neural: {_PT[ACTIONS[top]]} ({round(probs[top] * 100)}%)",
            confidence=probs[top],
            probs=tuple(probs),
        )
        return _choose(logits, obs)

    def insight(self) -> BotInsight | None:
        return self._last_insight
