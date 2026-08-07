"""EXPERIMENTO (pré-registrado): o Expert fica melhor com a técnica do Adaptativo?

Testa se sobrepor a EXPLORAÇÃO do AdaptiveBot (modelar fold_to_bet do oponente e
desviar) na política do Expert (ONNX, GTO/mista) o deixa MELHOR — sem confundir ganho
com OVERFITTING. Protocolo desenhado por 4 agentes (workflow) e pré-registrado aqui:

- PAREADO por baralho: baseline (Expert puro) e OM (Expert+exploração) jogam os MESMOS
  seeds; a métrica é a DIFERENÇA por mão d_i (reduz a variância enorme do poker).
- DUAS variantes: V1 (tilt uniforme, fiel/ingênua do AdaptiveBot) e V2 (separa BLEFE de
  VALOR — modula pela massa que a rede já dá a cada ação).
- CALIBRAÇÃO (escolhe k) vs TESTE (held-out) com implementações de vilão e seeds
  disjuntas; ambas continuam sendo arquétipos sintéticos, não pessoas independentes.
- IC familiar por BOOTSTRAP pareado de 30 blocos de match reinicializados e correção
  Bonferroni (poker tem cauda pesada e dependência serial dentro de bloco). Taxa de
  decisões ALTERADAS pelo warp
  (se ~0, o efeito é ruído). Sanity: k=0 => OM ≡ baseline.
- CRITÉRIO DE PROMOÇÃO: promove só se (1) existe desenho externo pré-registrado com
  margem e MDE, (2) a precisão observada suporta o MDE, (3) ganha no sub-pool
  EXPLORÁVEL, (4) é NÃO-INFERIOR no ROBUSTO e (5) o controle random permanece dentro
  de uma margem de equivalência pré-registrada.
  Sem a pré-especificação completa: REPROVA e mantém OFF.

Uso: defina `POKER_OM_PREREG_PATH` para o receipt JSON externo congelado e execute
`uv run python scripts/expert_om_experiment.py [n_test] [n_calib]`.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import sys
from pathlib import Path

from poker_arena.application.bot_factory import expert_model_path
from poker_arena.bots._policy import raise_size
from poker_arena.bots.heuristic_bot import postflop_strength, preflop_strength
from poker_arena.bots.ml_bot import MLBot, jitter_raise, sample_action
from poker_arena.bots.observation import Observation, observation_for
from poker_arena.bots.opponent_model import OpponentModel
from poker_arena.engine.actions import Action, ActionType
from poker_arena.engine.game import Hand
from poker_arena.engine.player import Player, PlayerStatus
from poker_arena.ml.encoder import encode, to_action

_MODEL = expert_model_path()
_EXPECTED_GROUP_SIZES = {"EXPLORAVEL": 3, "ROBUSTO": 2, "CONTROLE": 1}
_PREREG_MAX_BYTES = 64 * 1024
_PREREG_FIELDS = frozenset(
    {
        "schema_version",
        "experiment_id",
        "frozen_reference",
        "power_analysis_reference",
        "minimum_detectable_effect_bb100",
        "noninferiority_margin_bb100",
        "control_equivalence_margin_bb100",
        "family_size",
        "required_blocks",
        "block_unit",
    }
)


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key in pre-registration receipt")
        result[key] = value
    return result


def load_preregistration(path: str | Path) -> tuple[dict[str, object], str]:
    """Load a content-addressed external design receipt before expensive work."""

    receipt_path = Path(path)
    payload = receipt_path.read_bytes()
    if not payload or len(payload) > _PREREG_MAX_BYTES:
        raise ValueError("pre-registration receipt has an invalid size")
    try:
        parsed = json.loads(payload, object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("pre-registration receipt is not canonical JSON") from exc
    if not isinstance(parsed, dict) or set(parsed) != _PREREG_FIELDS:
        raise ValueError("pre-registration receipt fields do not match schema v1")
    if parsed.get("schema_version") != 1:
        raise ValueError("unsupported pre-registration schema")
    for field in ("experiment_id", "frozen_reference", "power_analysis_reference"):
        value = parsed.get(field)
        if (
            not isinstance(value, str)
            or value != value.strip()
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{7,255}", value)
        ):
            raise ValueError(f"invalid pre-registration field: {field}")
    if parsed.get("family_size") != sum(_EXPECTED_GROUP_SIZES.values()):
        raise ValueError("pre-registration family_size does not match the six comparisons")
    if parsed.get("required_blocks") != 30:
        raise ValueError("pre-registration must declare exactly 30 reset match blocks")
    if parsed.get("block_unit") != "independent_reset_match_block":
        raise ValueError("pre-registration block unit is incompatible")
    for field, allow_zero in (
        ("minimum_detectable_effect_bb100", False),
        ("noninferiority_margin_bb100", True),
        ("control_equivalence_margin_bb100", True),
    ):
        value = parsed.get(field)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or (float(value) < 0.0 if allow_zero else float(value) <= 0.0)
        ):
            raise ValueError(f"invalid pre-registration field: {field}")
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    return parsed, digest


# ----------------- VILÕES (arquétipos com vazamentos conhecidos) -----------------
class CallingStation:  # paga tudo, nunca aumenta/desiste -> fold_to_bet ~0 (não blefável)
    def __init__(self, seed: int = 0) -> None:
        pass

    def act(self, obs: Observation) -> Action:
        if ActionType.CHECK in obs.legal_actions:
            return Action(ActionType.CHECK)
        if ActionType.CALL in obs.legal_actions:
            return Action(ActionType.CALL)
        return Action(ActionType.FOLD)


class Nit:  # over-folder: desiste de qualquer aposta sem mão forte -> fold_to_bet ALTO
    def __init__(self, seed: int = 0) -> None:
        pass

    def act(self, obs: Observation) -> Action:
        s = (
            postflop_strength(obs.hole, obs.board)
            if len(obs.board) >= 3
            else preflop_strength(obs.hole)
        )
        if obs.to_call == 0:
            if s > 0.85 and ActionType.RAISE in obs.legal_actions:
                return Action(ActionType.RAISE, raise_size(obs))
            return Action(ActionType.CHECK)
        if s >= 0.80 and ActionType.CALL in obs.legal_actions:
            return Action(ActionType.CALL)
        return (
            Action(ActionType.FOLD)
            if ActionType.FOLD in obs.legal_actions
            else Action(ActionType.CHECK)
        )


class CalibrationOverfolder:
    """Arquétipo usado somente para escolher k; não aparece na bateria held-out.

    Ele pertence à mesma família conceitual do Nit, mas usa limiares distintos. Isso
    evita reutilizar literalmente a implementação de teste sem fingir independência
    populacional entre dois bots sintéticos.
    """

    def __init__(self, seed: int = 0) -> None:
        pass

    def act(self, obs: Observation) -> Action:
        strength = (
            postflop_strength(obs.hole, obs.board)
            if len(obs.board) >= 3
            else preflop_strength(obs.hole)
        )
        if obs.to_call == 0:
            if strength > 0.78 and ActionType.RAISE in obs.legal_actions:
                return Action(ActionType.RAISE, raise_size(obs))
            return Action(ActionType.CHECK)
        if strength >= 0.72 and ActionType.CALL in obs.legal_actions:
            return Action(ActionType.CALL)
        return (
            Action(ActionType.FOLD)
            if ActionType.FOLD in obs.legal_actions
            else Action(ActionType.CHECK)
        )


class Maniac:  # aumenta demais (60%)
    def __init__(self, seed: int = 0) -> None:
        self.rng = random.Random(seed)  # noqa: S311 - preregistered simulation stream

    def act(self, obs: Observation) -> Action:
        if ActionType.RAISE in obs.legal_actions and self.rng.random() < 0.6:
            return Action(ActionType.RAISE, raise_size(obs))
        if obs.to_call == 0:
            return Action(ActionType.CHECK)
        if ActionType.CALL in obs.legal_actions:
            return Action(ActionType.CALL)
        return Action(ActionType.FOLD)


class ExpertMirror:  # o próprio Expert (robusto, sem hábito estável pra punir)
    def __init__(self, seed: int = 0) -> None:
        self.bot = MLBot(_MODEL, seed=seed)

    def act(self, obs: Observation) -> Action:
        return self.bot.act(obs)


def _villain_factory(name: str):
    from poker_arena.bots import HeuristicBot, MonteCarloBot, RandomBot

    return {
        "calibration_overfolder": CalibrationOverfolder,
        "overfolder": Nit,
        "station": CallingStation,
        "maniac": Maniac,
        "random": RandomBot,
        "heuristic": HeuristicBot,
        "montecarlo": MonteCarloBot,
        "expert_mirror": ExpertMirror,
    }[name]


def _act_type(a: Action) -> str:
    return {
        ActionType.FOLD: "fold",
        ActionType.CHECK: "check",
        ActionType.CALL: "call",
        ActionType.RAISE: "raise",
        ActionType.ALL_IN: "all_in",
    }[a.type]


# ----------------- EXPERT baseline e EXPERT-OM (V1 / V2) -----------------
_DIR = (-1.0, -0.5, 0.5, 1.0, 0.5)  # fold, check_call, raise_half, raise_pot, all_in


class ExpertHero:
    """Expert puro (variant=None) ou Expert+exploração. O warp desloca as probs da rede
    conforme o read do oponente, FIEL à fórmula linear do AdaptiveBot (b = k·(fold_to_bet
    −0.5)·read_confidence). V1: tilt uniforme (defeito conhecido: vira maniac vs station).
    V2: modula pela massa que a rede já dá (blefa só mão marginal; valoriza vs station)."""

    def __init__(
        self, seed: int, om: OpponentModel | None = None, k: float = 0.0, variant: str | None = None
    ) -> None:
        self._bot = MLBot(_MODEL, seed=seed)
        self._om, self._k, self._variant = om, k, variant
        self._np = self._bot._np
        self._rng = random.Random(seed)  # noqa: S311 - preregistered simulation stream
        self.altered = 0  # nº de decisões em que o warp mudou a ação favorita
        self.active = 0  # nº de decisões com warp ativo (read_confidence>0)
        self.decisions = 0

    def reseed(self, seed: int) -> None:
        self._rng = random.Random(seed)  # noqa: S311 - deterministic reseed
        self._bot._rng = random.Random(seed)  # noqa: S311 - deterministic reseed

    def _warp(self, probs: list[float], obs: Observation) -> list[float]:
        b = self._k * (self._om.fold_to_bet - 0.5) * self._om.read_confidence
        if b == 0.0:
            return probs
        lp = [math.log(p + 1e-12) for p in probs]
        if self._variant == "v1":
            for i in range(5):
                lp[i] += b * _DIR[i]
        else:  # v2: separa blefe (mão marginal) de valor (massa em raise)
            if b > 0:  # over-folder -> blefa SÓ em mão marginal (rede já quer fold/check)
                marginal = probs[0] + probs[1]
                for i in range(5):
                    lp[i] += b * marginal * _DIR[i]
            else:  # station -> suprime blefe, engrossa valor onde a rede já dá massa a raise
                lp[0] += (-b) * probs[1]  # marginal: prefere check_call a blefar
                lp[2] += (-b) * probs[2]  # value bet existente mais grosso
                lp[3] += (-b) * probs[3]
        mx = max(lp)
        exps = [math.exp(v - mx) if probs[i] > 0 else 0.0 for i, v in enumerate(lp)]
        tot = sum(exps) or 1.0
        return [e / tot for e in exps]

    def act(self, obs: Observation) -> Action:
        feats = self._np.asarray([encode(obs)], dtype=self._np.float32)
        logits = self._bot._session.run(None, {self._bot._input: feats})[0][0].tolist()
        probs = self._bot._softmax_legal(logits, obs)
        if self._variant and self._om is not None and self._k > 0 and self._om.read_confidence > 0:
            self.decisions += 1
            self.active += 1
            warped = self._warp(probs, obs)
            if max(range(5), key=lambda i: warped[i]) != max(range(5), key=lambda i: probs[i]):
                self.altered += 1
            probs = warped
        elif self._variant:
            self.decisions += 1
        chosen = sample_action(probs, self._rng, self._bot._temperature, self._bot._min_prob_ratio)
        return jitter_raise(to_action(obs, chosen), obs, self._rng, self._bot._sizing_jitter)


# ----------------- loop pareado (alimenta o modelo de oponente) -----------------
def _play_hand(hand: Hand, hero: ExpertHero, villains: list, om: OpponentModel | None) -> None:
    guard = 0
    while guard < 500:
        guard += 1
        while not hand.round_complete():
            seat = hand.to_act
            obs = observation_for(hand)
            if seat == 0:
                action = hero.act(obs)
            else:
                action = villains[seat - 1].act(obs)
                if om is not None:
                    om.observe(_act_type(action), to_call=obs.to_call)
            hand.apply(action)
        live = [p for p in hand.players if p.status != PlayerStatus.FOLDED]
        if len(live) <= 1 or len(hand.board) >= 5:
            hand.resolve()
            return
        hand.advance_street()
    raise RuntimeError("hand exceeded the 500-step safety bound")


def _run(
    villain: str,
    seeds: list[int],
    k: float,
    variant: str | None,
    *,
    n: int = 6,
    stack: int = 1000,
    sb: int = 10,
    bb: int = 20,
    match_blocks: int = 30,
) -> tuple[list[float], ExpertHero]:
    if match_blocks < 2 or len(seeds) < match_blocks:
        raise ValueError("run requires at least one hand in each independent match block")
    Villain = _villain_factory(villain)
    out: list[float] = []
    aggregate_altered = aggregate_active = aggregate_decisions = 0
    quotient, remainder = divmod(len(seeds), match_blocks)
    offset = 0
    last_hero: ExpertHero | None = None
    for block_index in range(match_blocks):
        count = quotient + (1 if block_index < remainder else 0)
        block_seeds = seeds[offset : offset + count]
        offset += count
        om = OpponentModel() if variant else None
        hero = ExpertHero(seed=7 + block_index, om=om, k=k, variant=variant)
        villains = [Villain(10_000 * (block_index + 1) + 200 + i) for i in range(n - 1)]
        for hand_seed in block_seeds:
            hero.reseed(hand_seed)
            players = [Player(f"P{i}", stack) for i in range(n)]
            hand = Hand(players, button=hand_seed % n, small_blind=sb, big_blind=bb, seed=hand_seed)
            hand.start()
            _play_hand(hand, hero, villains, om)
            out.append((players[0].stack - stack) / bb)
        aggregate_altered += hero.altered
        aggregate_active += hero.active
        aggregate_decisions += hero.decisions
        last_hero = hero
    if last_hero is None:  # guarded by len(seeds) >= match_blocks
        raise RuntimeError("no match block was executed")
    last_hero.altered = aggregate_altered
    last_hero.active = aggregate_active
    last_hero.decisions = aggregate_decisions
    return out, last_hero


# ----------------- estatística -----------------
def bootstrap_ci(
    d: list[float],
    iters: int = 10000,
    seed: int = 1,
    chunk: int = 500,
    *,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """Percentile bootstrap interval for independent values.

    This helper is retained for unit-level diagnostics. Promotion uses
    :func:`paired`, which first aggregates consecutive hands into independent
    match blocks and applies a family-wise alpha.
    """
    import numpy as np

    if not d:
        raise ValueError("bootstrap sample must be non-empty")
    if iters <= 0 or chunk <= 0:
        raise ValueError("bootstrap iterations and chunk must be positive")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be between zero and one")
    arr = np.asarray(d, dtype=np.float64)
    if not np.isfinite(arr).all():
        raise ValueError("bootstrap sample must contain only finite values")
    n = len(arr)
    rng = np.random.default_rng(seed)
    means = np.empty(iters)
    done = 0
    while done < iters:
        c = min(chunk, iters - done)
        idx = rng.integers(0, n, size=(c, n))
        means[done : done + c] = arr[idx].mean(axis=1)
        done += c
    tail = 100.0 * alpha / 2.0
    return float(np.percentile(means, tail)), float(np.percentile(means, 100.0 - tail))


def _block_bootstrap_ci(
    block_sums: list[float],
    block_counts: list[int],
    *,
    alpha: float,
    iters: int = 10000,
    seed: int = 1,
    chunk: int = 500,
) -> tuple[float, float]:
    """Cluster bootstrap over independently reset match blocks, retaining weights."""
    import numpy as np

    if (
        not block_sums
        or len(block_sums) != len(block_counts)
        or any(count <= 0 for count in block_counts)
    ):
        raise ValueError("block bootstrap requires non-empty aligned blocks")
    if iters <= 0 or chunk <= 0 or not 0.0 < alpha < 1.0:
        raise ValueError("invalid block-bootstrap configuration")
    sums = np.asarray(block_sums, dtype=np.float64)
    counts = np.asarray(block_counts, dtype=np.int64)
    if not np.isfinite(sums).all():
        raise ValueError("block sums must be finite")
    rng = np.random.default_rng(seed)
    means = np.empty(iters, dtype=np.float64)
    done = 0
    n_blocks = len(sums)
    while done < iters:
        current = min(chunk, iters - done)
        indices = rng.integers(0, n_blocks, size=(current, n_blocks))
        means[done : done + current] = sums[indices].sum(axis=1) / counts[indices].sum(axis=1)
        done += current
    tail = 100.0 * alpha / 2.0
    return float(np.percentile(means, tail)), float(np.percentile(means, 100.0 - tail))


def paired(
    base: list[float],
    om: list[float],
    *,
    required_blocks: int = 30,
    familywise_comparisons: int = 6,
) -> dict:
    """Paired bb/100 estimate with contiguous-block, multiplicity-adjusted CI."""
    if not base or len(base) != len(om):
        raise ValueError("paired samples must be non-empty and have equal length")
    if required_blocks < 2 or familywise_comparisons < 1:
        raise ValueError("invalid block or multiplicity design")
    n = len(base)
    d = [om[i] - base[i] for i in range(n)]
    if not all(math.isfinite(value) for value in [*base, *om, *d]):
        raise ValueError("paired samples must contain only finite values")
    if n < required_blocks:
        raise ValueError(f"paired design requires at least {required_blocks} hands")

    quotient, remainder = divmod(n, required_blocks)
    block_sums: list[float] = []
    block_counts: list[int] = []
    offset = 0
    for block_index in range(required_blocks):
        count = quotient + (1 if block_index < remainder else 0)
        block = d[offset : offset + count]
        block_sums.append(sum(block))
        block_counts.append(count)
        offset += count
    familywise_alpha = 0.05 / familywise_comparisons
    lo, hi = _block_bootstrap_ci(
        block_sums,
        block_counts,
        alpha=familywise_alpha,
    )
    return {
        "base": 100 * sum(base) / n,
        "om": 100 * sum(om) / n,
        "delta": 100 * sum(d) / n,
        "lo": 100 * lo,
        "hi": 100 * hi,
        "n_eff": sum(1 for x in d if x != 0),
        "n_hands": n,
        "n_blocks": required_blocks,
        "block_unit": "independent_reset_match_block",
        "familywise_comparisons": familywise_comparisons,
        "familywise_alpha": familywise_alpha,
    }


def promotion_verdict(
    groups: dict[str, list[dict]],
    *,
    noninferiority_margin: float | None = None,
    power_analysis_id: str | None = None,
    minimum_detectable_effect: float | None = None,
    control_equivalence_margin: float | None = None,
    required_blocks: int = 30,
) -> dict[str, bool]:
    """Apply the pre-registered gate to held-out confidence intervals.

    Promotion is fail-closed unless an external pre-registration supplies both a
    justified non-inferiority margin and a minimum detectable effect (MDE).  The MDE is
    also used as a precision gate: every simultaneous interval must have half-width no
    larger than the declared MDE.  This is deliberately not advertised as a post-hoc
    power calculation.

    Non-inferiority is established by the *lower* confidence bound being above the
    negative loss tolerance. The negative-control interval must remain wholly
    inside a separately pre-registered equivalence margin; movement in either
    direction is therefore treated as a protocol red flag.
    """
    explorable = groups.get("EXPLORAVEL", [])
    robust = groups.get("ROBUSTO", [])
    control = groups.get("CONTROLE", [])
    all_intervals = [*explorable, *robust, *control]
    group_contract_valid = (
        set(groups) == set(_EXPECTED_GROUP_SIZES)
        and all(
            isinstance(groups.get(group), list) and len(groups[group]) == expected_size
            for group, expected_size in _EXPECTED_GROUP_SIZES.items()
        )
        and all(
            isinstance(interval, dict)
            and interval.get("group") == group
            and isinstance(interval.get("comparison_id"), str)
            and bool(interval["comparison_id"].strip())
            for group in _EXPECTED_GROUP_SIZES
            for interval in groups[group]
        )
        and len(
            {
                interval["comparison_id"]
                for group in _EXPECTED_GROUP_SIZES
                for interval in groups[group]
            }
        )
        == sum(_EXPECTED_GROUP_SIZES.values())
    )
    valid_margin = (
        noninferiority_margin is not None
        and math.isfinite(noninferiority_margin)
        and noninferiority_margin >= 0.0
    )
    valid_mde = (
        minimum_detectable_effect is not None
        and math.isfinite(minimum_detectable_effect)
        and minimum_detectable_effect > 0.0
    )
    valid_control_margin = (
        control_equivalence_margin is not None
        and math.isfinite(control_equivalence_margin)
        and control_equivalence_margin >= 0.0
    )
    valid_blocks = type(required_blocks) is int and required_blocks >= 2
    valid_power_receipt = bool(
        isinstance(power_analysis_id, str)
        and re.fullmatch(r"sha256:[0-9a-f]{64}", power_analysis_id)
    )
    design_preregistered = valid_power_receipt and (
        valid_margin and valid_mde and valid_control_margin and valid_blocks
    )
    loss_tolerance = float(noninferiority_margin) if valid_margin else math.nan
    mde_limit = float(minimum_detectable_effect) if valid_mde else math.nan
    intervals_valid = (
        group_contract_valid
        and bool(all_intervals)
        and all(
            isinstance(s, dict)
            and all(
                isinstance(s.get(key), (int, float))
                and not isinstance(s.get(key), bool)
                and math.isfinite(float(s[key]))
                for key in ("lo", "hi", "familywise_alpha")
            )
            and float(s["lo"]) <= float(s["hi"])
            and type(s.get("n_blocks")) is int
            and s["n_blocks"] >= required_blocks
            and s.get("block_unit") == "independent_reset_match_block"
            and 0.0 < float(s["familywise_alpha"]) <= 0.05 / len(all_intervals)
            for s in all_intervals
        )
    )
    precision_supports_mde = (
        bool(design_preregistered)
        and intervals_valid
        and all((float(s["hi"]) - float(s["lo"])) / 2.0 <= mde_limit for s in all_intervals)
    )
    explorable_gain = (
        intervals_valid
        and len(explorable) >= 2
        and sum(float(s["lo"]) > 0 for s in explorable) >= 2
    )
    robust_noninferior = (
        bool(robust)
        and bool(design_preregistered)
        and all(float(s["lo"]) >= -loss_tolerance for s in robust)
    )
    control_limit = float(control_equivalence_margin) if valid_control_margin else math.nan
    control_ok = (
        bool(control)
        and bool(design_preregistered)
        and intervals_valid
        and all(
            float(s["lo"]) >= -control_limit and float(s["hi"]) <= control_limit for s in control
        )
    )
    return {
        "group_contract_valid": group_contract_valid,
        "design_preregistered": design_preregistered,
        "intervals_valid": intervals_valid,
        "precision_supports_mde": precision_supports_mde,
        "explorable_gain": explorable_gain,
        "robust_noninferior": robust_noninferior,
        "control_ok": control_ok,
        "promote": (
            design_preregistered
            and precision_supports_mde
            and explorable_gain
            and robust_noninferior
            and control_ok
        ),
    }


def main() -> None:
    n_test = int(sys.argv[1]) if len(sys.argv) > 1 else 12000
    n_calib = int(sys.argv[2]) if len(sys.argv) > 2 else 6000
    prereg_path = os.environ.get("POKER_OM_PREREG_PATH", "").strip()
    if not prereg_path:
        raise RuntimeError("POKER_OM_PREREG_PATH is required before running the experiment")
    prereg, prereg_sha256 = load_preregistration(prereg_path)
    if not _MODEL.exists():
        print("Expert ONNX não encontrado.")
        return
    rc = random.Random(111)  # noqa: S311 - fixed calibration panel
    calib_seeds = [rc.randrange(1 << 30) for _ in range(n_calib)]
    rt = random.Random(999999)  # noqa: S311 - disjoint fixed test panel
    test_seeds = [rt.randrange(1 << 30) for _ in range(n_test)]

    print(
        f"# EXPERIMENTO Expert opponent-aware (pre-registrado) | calib {n_calib} / teste {n_test} maos"
    )
    print(
        "# pareado por baralho; bootstrap de 30 blocos reinicializados; IC familiar "
        f"Bonferroni. prereg={prereg_sha256}. seeds e implementacoes calib!=teste.\n"
    )

    EXPLOITABLE = ["overfolder", "station", "maniac"]
    # montecarlo dropado do pool: 5 bots simulando equity/decisão o tornam ~10x mais lento
    # e inviabilizam o run. heuristic (benchmark canônico do equity guard) + expert_mirror
    # (self-play) são juízes robustos suficientes pro teste de não-inferioridade.
    ROBUST = ["heuristic", "expert_mirror"]
    CONTROL = ["random"]
    base_cache: dict[str, list[float]] = {}

    def base_test(v: str) -> list[float]:
        if v not in base_cache:
            base_cache[v] = _run(v, test_seeds, 0.0, None)[0]
        return base_cache[v]

    # ---- CALIBRAÇÃO: implementação distinta, usada somente para escolher k ----
    print("## CALIBRACAO (calibration_overfolder, seeds de CALIB) — escolhe k")
    base_c = _run("calibration_overfolder", calib_seeds, 0.0, None)[0]
    best = {}
    for variant in ("v1", "v2"):
        bk, bg = 0.0, -1e9
        for k in (1.0, 2.0, 4.0):
            om, _h = _run("calibration_overfolder", calib_seeds, k, variant)
            s = paired(base_c, om)
            print(
                f"  {variant} k={k}: d {s['delta']:+7.1f} [{s['lo']:+.1f},{s['hi']:+.1f}] "
                f"altera {100 * _h.altered / max(_h.active, 1):.0f}%"
            )
            if s["delta"] > bg:
                bg, bk = s["delta"], k
        best[variant] = bk
        print(f"  >>> {variant}: k*={bk}\n")

    # ---- TESTE: held-out, seeds de TESTE, ambas as variantes ----
    for variant in ("v1", "v2"):
        k = best[variant]
        print(f"## TESTE held-out — {variant.upper()} k={k}  (seeds de TESTE, disjuntos)")
        sub = {"EXPLORAVEL": [], "ROBUSTO": [], "CONTROLE": []}
        for grp, vils in (("EXPLORAVEL", EXPLOITABLE), ("ROBUSTO", ROBUST), ("CONTROLE", CONTROL)):
            for v in vils:
                om, h = _run(v, test_seeds, k, variant)
                s = paired(base_test(v), om)
                s["comparison_id"] = v
                s["group"] = grp
                flag = ""
                if s["lo"] > 0:
                    flag = " GANHO(sig)"
                elif s["hi"] < 0:
                    flag = " PERDA(sig)"
                alt = 100 * h.altered / max(h.active, 1)
                print(
                    f"  [{grp:10s}] {v:14s}: base {s['base']:+7.1f} | OM {s['om']:+7.1f} | "
                    f"d {s['delta']:+7.1f} [{s['lo']:+.1f},{s['hi']:+.1f}] alt {alt:.0f}%{flag}"
                )
                if grp in sub:
                    sub[grp].append(s)
        # veredito mecânico
        gate = promotion_verdict(
            sub,
            noninferiority_margin=prereg["noninferiority_margin_bb100"],
            power_analysis_id=prereg_sha256,
            minimum_detectable_effect=prereg["minimum_detectable_effect_bb100"],
            control_equivalence_margin=prereg["control_equivalence_margin_bb100"],
            required_blocks=prereg["required_blocks"],
        )
        verdict = "PROMOVE" if gate["promote"] else "REPROVA (mantem OFF, como o equity guard)"
        print(
            f"  >>> VEREDITO {variant.upper()}: "
            f"desenho_pre_registrado={gate['design_preregistered']} "
            f"intervalos_validos={gate['intervals_valid']} "
            f"precisao_mde={gate['precision_supports_mde']} "
            f"exploravel_ganha={gate['explorable_gain']} "
            f"robusto_nao_inferior={gate['robust_noninferior']} "
            f"controle_ok={gate['control_ok']} -> {verdict}\n"
        )


if __name__ == "__main__":
    main()
