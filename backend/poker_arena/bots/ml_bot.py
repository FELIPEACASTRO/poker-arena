"""MLBot — nível 🔴 Expert por IA treinada (política neural via ONNX).

Carrega uma política ONNX compatível com o contrato declarado e implementa `Bot`:
encoder v2 multientrada → dez logits → máscara sem aliases → decisão modal ou mista.
O padrão preserva a política bruta (temperatura 1, sem corte e sem jitter); qualquer
pós-processamento não neutro precisa ser explícito ou aprovado no manifesto.

onnxruntime/numpy entram só aqui (import dentro do __init__): o resto do backend
não depende deles a menos que o Expert seja usado.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from ..engine.actions import Action, ActionType
from ..engine.cards import make_rng
from ..ml.action_space_v2 import (
    ACTIONS_V2,
    N_ACTIONS_V2,
    legal_mask_v2,
    to_action_v2,
)
from ..ml.action_space_v2 import (
    REVISION as ACTION_SPACE_V2_REVISION,
)
from ..ml.encoder import ACTIONS, N_ACTIONS, encode, legal_mask, to_action
from ..ml.encoder_v2 import REVISION as ENCODER_V2_REVISION
from ..ml.encoder_v2 import encode_v2
from ..model_artifacts import (
    ModelArtifactUnavailable,
    model_manifest_path,
    revalidate_model_artifact_identity,
    verify_evaluation_candidate,
    verify_model_artifact,
    verify_runtime_contract,
)
from .insight import BotInsight
from .observation import Observation

# Rótulos curtos das ações discretas v1/v2 (glass-box).
_PT = {
    "fold": "desistir",
    "check_call": "pagar",
    "raise_half": "aumentar ½",
    "raise_pot": "aumentar pote",
    "all_in": "all-in",
    "raise_min": "aumentar mínimo",
    "raise_033_pot": "aumentar ⅓ do pote",
    "raise_050_pot": "aumentar ½ pote",
    "raise_075_pot": "aumentar ¾ do pote",
    "raise_100_pot": "aumentar o pote",
    "raise_150_pot": "aumentar 1½ pote",
    "raise_200_pot": "aumentar 2 potes",
}

# Defaults neutros: preservam exatamente a distribuição legal da rede e o sizing
# discreto produzido por ``to_action``. Os antigos 0.75/0.15/0.12 não têm validação
# ligada ao hash do modelo e, portanto, não podem alterar a política por padrão.
TEMPERATURE = 1.0
MIN_PROB_RATIO = 0.0
SIZING_JITTER = 0.0


class ExpertInferenceError(RuntimeError):
    """Closed-code failure raised by the scientific evaluation lane."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"expert inference rejected [{code}]")


def sample_action(
    probs: list[float],
    rng: random.Random,
    temperature: float = TEMPERATURE,
    min_prob_ratio: float = MIN_PROB_RATIO,
) -> int:
    """Sorteia um índice da distribuição (estratégia mista), com salvaguardas.

    - Piso: só participam ações com prob >= `min_prob_ratio` × prob da favorita —
      nunca se sorteia uma jogada que a rede considera claramente pior.
    - Temperatura: pesos = p^(1/τ); τ<1 concentra na favorita (τ→0 = argmax).
    """
    top = max(probs)
    if top <= 0.0:
        return probs.index(top)
    kept = [(i, p) for i, p in enumerate(probs) if p > 0.0 and p >= min_prob_ratio * top]
    if temperature <= 1e-6 or len(kept) == 1:
        return max(kept, key=lambda x: x[1])[0]
    log_weights = [(i, math.log(p) / temperature) for i, p in kept]
    max_log_weight = max(value for _, value in log_weights)
    weights = [(i, math.exp(value - max_log_weight)) for i, value in log_weights]
    total = sum(w for _, w in weights)
    if not math.isfinite(total) or total <= 0.0:
        return max(kept, key=lambda x: x[1])[0]
    r = rng.random() * total
    acc = 0.0
    for i, w in weights:
        acc += w
        if r <= acc:
            return i
    return weights[-1][0]


def jitter_raise(
    action: Action, obs: Observation, rng: random.Random, jitter: float = SIZING_JITTER
) -> Action:
    """Varia o TAMANHO do aumento em ±jitter, dentro dos limites legais.

    Tamanhos sempre exatos (½ pote / pote) entregam o padrão pra um humano; um
    ruído pequeno não muda o EV de forma relevante e apaga a assinatura.
    """
    if action.type is not ActionType.RAISE or jitter <= 0.0:
        return action
    me = next(p for p in obs.players if p.seat == obs.seat)
    max_to = me.current_bet + me.stack
    scaled = round(action.amount * (1.0 + rng.uniform(-jitter, jitter)))
    return Action(ActionType.RAISE, max(obs.min_raise_to, min(scaled, max_to)))


class MLBot:
    """Deployable Expert bot; accepts only approved/promoted model manifests."""

    _manifest_env = "POKER_EXPERT_MANIFEST"
    _artifact_verifier = staticmethod(verify_model_artifact)
    _strict_inference = False

    def __init__(
        self,
        model_path: str | Path,
        name: str = "Rex (Expert)",
        *,
        manifest_path: str | Path | None = None,
        temperature: float | None = None,
        min_prob_ratio: float | None = None,
        sizing_jitter: float | None = None,
        equity_guard: bool = False,  # experimento reprovado na medição (ver acima)
        seed: int | None = None,
    ):
        import numpy as np
        import onnxruntime as ort

        path = Path(model_path)
        resolved_manifest = (
            Path(manifest_path)
            if manifest_path is not None
            else model_manifest_path(path, self._manifest_env)
        )
        artifact = self._artifact_verifier(path, "expert", manifest_path=resolved_manifest)
        self.name = name
        self._np = np
        try:
            self._session = ort.InferenceSession(
                str(artifact.path), providers=["CPUExecutionProvider"]
            )
        except Exception as exc:  # noqa: BLE001 - normalize runtime load as gate rejection
            raise ModelArtifactUnavailable("runtime_load_failed", str(exc)) from exc
        revalidate_model_artifact_identity(artifact)
        verify_runtime_contract(artifact, self._session.get_inputs(), self._session.get_outputs())
        entry = artifact.entry
        self._v2 = (
            entry.get("encoder_revision") == ENCODER_V2_REVISION
            and entry.get("action_space_revision") == ACTION_SPACE_V2_REVISION
        )
        self._input_names = tuple(item.name for item in self._session.get_inputs())
        self._actions = ACTIONS_V2 if self._v2 else ACTIONS
        self._action_count = N_ACTIONS_V2 if self._v2 else N_ACTIONS
        self._last_insight: BotInsight | None = None
        policy = artifact.inference_policy
        requested = (
            policy.temperature if temperature is None else temperature,
            policy.min_prob_ratio if min_prob_ratio is None else min_prob_ratio,
            policy.sizing_jitter if sizing_jitter is None else sizing_jitter,
        )
        if policy.source == "neutral" and requested != (
            TEMPERATURE,
            MIN_PROB_RATIO,
            SIZING_JITTER,
        ):
            raise ValueError("non-neutral inference policy must be approved in MANIFEST.json")
        if policy.source == "manifest" and requested != (
            policy.temperature,
            policy.min_prob_ratio,
            policy.sizing_jitter,
        ):
            raise ValueError("runtime inference policy must match the approved manifest")
        self._temperature, self._min_prob_ratio, self._sizing_jitter = requested
        self._decision_rule = policy.decision_rule
        self._supported_action_indices = frozenset(
            policy.supported_action_indices or range(self._action_count)
        )
        if not 0.0 <= self._temperature <= 10.0:
            raise ValueError("temperature must be within [0, 10]")
        if not 0.0 <= self._min_prob_ratio <= 1.0:
            raise ValueError("min_prob_ratio must be within [0, 1]")
        if not 0.0 <= self._sizing_jitter <= 1.0:
            raise ValueError("sizing_jitter must be within [0, 1]")
        if equity_guard:
            raise ValueError("equity_guard is a rejected experiment and cannot alter runtime")
        self._artifact = artifact
        self._rng = make_rng(seed)  # cripto em produção; reprodutível com seed

    def _softmax_legal(self, logits: list[float], obs: Observation) -> list[float]:
        """Distribuição da rede SÓ sobre as ações legais (ilegais ≈ 0)."""
        if len(logits) != self._action_count:
            raise ExpertInferenceError("output_shape_invalid")
        if any(not math.isfinite(float(value)) for value in logits):
            raise ExpertInferenceError("output_non_finite")
        legal = legal_mask_v2(obs) if self._v2 else legal_mask(obs)
        if not any(legal):
            raise ExpertInferenceError("legal_mask_empty")
        legal_modal = max(
            (index for index, is_legal in enumerate(legal) if is_legal),
            key=lambda index: logits[index],
        )
        if legal_modal not in self._supported_action_indices:
            raise ExpertInferenceError("unsupported_action_modal")
        mask = tuple(
            is_legal and index in self._supported_action_indices
            for index, is_legal in enumerate(legal)
        )
        if not any(mask):
            raise ExpertInferenceError("supported_legal_mask_empty")
        masked = self._np.array(
            [logits[i] if mask[i] else -self._np.inf for i in range(self._action_count)],
            dtype="float64",
        )
        masked -= masked.max()
        exps = self._np.exp(masked)  # exp(-inf) = 0
        total = float(exps.sum())
        if not math.isfinite(total) or total <= 0.0:
            raise ExpertInferenceError("distribution_invalid")
        probs = (exps / total).tolist()
        if any(not math.isfinite(float(value)) or value < 0.0 for value in probs):
            raise ExpertInferenceError("distribution_invalid")
        if not math.isclose(sum(probs), 1.0, rel_tol=1e-7, abs_tol=1e-9):
            raise ExpertInferenceError("distribution_invalid")
        return probs

    def _fallback_action(self, obs: Observation) -> Action:
        """Fail-safe determinístico quando o runtime neural não produz política válida."""
        legal = obs.legal_actions
        if ActionType.CHECK in legal:
            return Action(ActionType.CHECK)
        if ActionType.FOLD in legal:
            return Action(ActionType.FOLD)
        if ActionType.CALL in legal:
            return Action(ActionType.CALL)
        if ActionType.ALL_IN in legal:
            return Action(ActionType.ALL_IN)
        if ActionType.RAISE in legal:
            try:
                return to_action_v2(obs, 2) if self._v2 else to_action(obs, 2)
            except ValueError as exc:
                raise ExpertInferenceError("fallback_legal_state_inconsistent") from exc
        raise RuntimeError("expert_fallback_no_legal_action")

    def _fail_safe(self, obs: Observation, code: str) -> Action:
        action = self._fallback_action(obs)
        self._last_insight = BotInsight(
            kind="expert",
            label=f"Inferência neural recusada ({code}); fallback legal determinístico",
            confidence=0.0,
        )
        return action

    def act(self, obs: Observation) -> Action:
        try:
            probs = self.policy_distribution(obs)
        except ExpertInferenceError as exc:
            if self._strict_inference:
                raise
            return self._fail_safe(obs, exc.code)
        except Exception as exc:  # noqa: BLE001 - deploy isolates a failed neural decision
            if self._strict_inference:
                raise ExpertInferenceError("runtime_execution_failed") from exc
            return self._fail_safe(obs, "runtime_execution_failed")
        top = max(range(self._action_count), key=lambda i: probs[i])
        chosen = (
            top
            if self._decision_rule == "modal"
            else sample_action(probs, self._rng, self._temperature, self._min_prob_ratio)
        )
        if chosen == top:
            label = f"Rede neural: {_PT[self._actions[top]]} ({round(probs[top] * 100)}%)"
        else:  # estratégia mista em ação — o glass-box mostra o sorteio
            label = (
                f"Rede neural (mista): sorteou {_PT[self._actions[chosen]]} "
                f"({round(probs[chosen] * 100)}%); favorita {_PT[self._actions[top]]} "
                f"({round(probs[top] * 100)}%)"
            )
        positive = [probability for probability in probs if probability > 0.0]
        entropy = -sum(probability * math.log(probability) for probability in positive)
        normalized_entropy = entropy / math.log(len(positive)) if len(positive) > 1 else 0.0
        self._last_insight = BotInsight(
            kind="expert",
            label=label,
            confidence=probs[top],
            probs=tuple(probs),
            modal_action=self._actions[top],
            modal_probability=probs[top],
            executed_action=self._actions[chosen],
            executed_probability=probs[chosen],
            decision_rule=self._decision_rule,
            policy_entropy=min(1.0, max(0.0, normalized_entropy)),
        )
        action = to_action_v2(obs, chosen) if self._v2 else to_action(obs, chosen)
        return jitter_raise(action, obs, self._rng, self._sizing_jitter)

    def policy_distribution(self, obs: Observation) -> list[float]:
        """Return the exact legal distribution or raise a closed-code error."""

        try:
            if self._v2:
                encoded = encode_v2(obs)
                values = (
                    encoded.cards,
                    encoded.global_features,
                    encoded.seats,
                    encoded.history,
                    encoded.history_mask,
                    encoded.legal_mask,
                )
                feeds = {
                    name: self._np.asarray([value], dtype=self._np.float32)
                    for name, value in zip(self._input_names, values, strict=True)
                }
            else:
                feeds = {
                    self._input_names[0]: self._np.asarray([encode(obs)], dtype=self._np.float32)
                }
            raw_outputs = self._session.run(None, feeds)
            if len(raw_outputs) != 1 or getattr(raw_outputs[0], "shape", None) != (
                1,
                self._action_count,
            ):
                raise ExpertInferenceError("output_shape_invalid")
            return self._softmax_legal(raw_outputs[0][0].tolist(), obs)
        except ExpertInferenceError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalize all runtime failures
            raise ExpertInferenceError("runtime_execution_failed") from exc

    def insight(self) -> BotInsight | None:
        return self._last_insight


class EvaluationMLBot(MLBot):
    """Offline-only Expert evaluator for a governed ``candidate`` artifact.

    This class is deliberately absent from ``BotFactory``.  Its verifier rejects
    approved/promoted artifacts, while :class:`MLBot` rejects candidates, keeping
    research evaluation and deployment as non-overlapping capabilities.
    """

    _manifest_env = "POKER_EXPERT_CANDIDATE_MANIFEST"
    _artifact_verifier = staticmethod(verify_evaluation_candidate)
    _strict_inference = True

    def __init__(
        self,
        model_path: str | Path,
        name: str = "Rex (Evaluation Candidate)",
        *,
        manifest_path: str | Path | None = None,
        temperature: float | None = None,
        min_prob_ratio: float | None = None,
        sizing_jitter: float | None = None,
        equity_guard: bool = False,
        seed: int | None = None,
    ) -> None:
        super().__init__(
            model_path,
            name,
            manifest_path=manifest_path,
            temperature=temperature,
            min_prob_ratio=min_prob_ratio,
            sizing_jitter=sizing_jitter,
            equity_guard=equity_guard,
            seed=seed,
        )
