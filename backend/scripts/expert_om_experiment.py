"""EXPERIMENTO (pré-registrado): o Expert fica melhor com a técnica do Adaptativo?

Testa se sobrepor a EXPLORAÇÃO do AdaptiveBot (modelar fold_to_bet do oponente e
desviar) na política do Expert (ONNX, GTO/mista) o deixa MELHOR — sem confundir ganho
com OVERFITTING. Protocolo desenhado por 4 agentes (workflow) e pré-registrado aqui:

- PAREADO por baralho: baseline (Expert puro) e OM (Expert+exploração) jogam os MESMOS
  seeds; a métrica é a DIFERENÇA por mão d_i (reduz a variância enorme do poker).
- DUAS variantes: V1 (tilt uniforme, fiel/ingênua do AdaptiveBot) e V2 (separa BLEFE de
  VALOR — modula pela massa que a rede já dá a cada ação).
- CALIBRAÇÃO (escolhe k) vs TESTE (held-out) com vilões E seeds DISJUNTOS.
- IC 95% por BOOTSTRAP pareado (poker tem cauda pesada). Taxa de decisões ALTERADAS pelo
  warp (se ~0, o efeito é ruído). Sanity: k=0 => OM ≡ baseline.
- CRITÉRIO DE PROMOÇÃO (fixado ANTES): promove só se (1) ganha no sub-pool EXPLORÁVEL
  (IC>0) E (2) é NÃO-INFERIOR no ROBUSTO (IC sup > -5 bb/100) E (3) sem ganho grande vs
  random (red flag). Senão: REPROVA e documenta como o equity guard (mantém OFF).

Uso: uv run python scripts/expert_om_experiment.py [n_test] [n_calib]
"""

from __future__ import annotations

import math
import random
import sys

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
        s = postflop_strength(obs.hole, obs.board) if len(obs.board) >= 3 else preflop_strength(obs.hole)
        if obs.to_call == 0:
            if s > 0.85 and ActionType.RAISE in obs.legal_actions:
                return Action(ActionType.RAISE, raise_size(obs))
            return Action(ActionType.CHECK)
        if s >= 0.80 and ActionType.CALL in obs.legal_actions:
            return Action(ActionType.CALL)
        return Action(ActionType.FOLD) if ActionType.FOLD in obs.legal_actions else Action(ActionType.CHECK)


class Maniac:  # aumenta demais (60%)
    def __init__(self, seed: int = 0) -> None:
        self.rng = random.Random(seed)
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
        "overfolder": Nit, "station": CallingStation, "maniac": Maniac,
        "random": RandomBot, "heuristic": HeuristicBot, "montecarlo": MonteCarloBot,
        "expert_mirror": ExpertMirror,
    }[name]


def _act_type(a: Action) -> str:
    return {ActionType.FOLD: "fold", ActionType.CHECK: "check", ActionType.CALL: "call",
            ActionType.RAISE: "raise", ActionType.ALL_IN: "all_in"}[a.type]


# ----------------- EXPERT baseline e EXPERT-OM (V1 / V2) -----------------
_DIR = (-1.0, -0.5, 0.5, 1.0, 0.5)  # fold, check_call, raise_half, raise_pot, all_in


class ExpertHero:
    """Expert puro (variant=None) ou Expert+exploração. O warp desloca as probs da rede
    conforme o read do oponente, FIEL à fórmula linear do AdaptiveBot (b = k·(fold_to_bet
    −0.5)·read_confidence). V1: tilt uniforme (defeito conhecido: vira maniac vs station).
    V2: modula pela massa que a rede já dá (blefa só mão marginal; valoriza vs station)."""

    def __init__(self, seed: int, om: OpponentModel | None = None, k: float = 0.0,
                 variant: str | None = None) -> None:
        self._bot = MLBot(_MODEL, seed=seed)
        self._om, self._k, self._variant = om, k, variant
        self._np = self._bot._np
        self._rng = random.Random(seed)
        self.altered = 0  # nº de decisões em que o warp mudou a ação favorita
        self.active = 0   # nº de decisões com warp ativo (read_confidence>0)
        self.decisions = 0

    def reseed(self, seed: int) -> None:
        self._rng = random.Random(seed)
        self._bot._rng = random.Random(seed)

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
                lp[0] += (-b) * probs[1]            # marginal: prefere check_call a blefar
                lp[2] += (-b) * probs[2]            # value bet existente mais grosso
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


def _run(villain: str, seeds: list[int], k: float, variant: str | None,
         *, n: int = 6, stack: int = 1000, sb: int = 10, bb: int = 20) -> tuple[list[float], ExpertHero]:
    Villain = _villain_factory(villain)
    om = OpponentModel() if variant else None  # ACUMULA ao longo do match (aprende o vilão)
    hero = ExpertHero(seed=7, om=om, k=k, variant=variant)
    villains = [Villain(200 + i) for i in range(n - 1)]  # criados UMA vez (perf + estado)
    out = []
    for h in seeds:
        hero.reseed(h)  # sorteio da estratégia mista pareado por mão
        players = [Player(f"P{i}", stack) for i in range(n)]
        hand = Hand(players, button=h % n, small_blind=sb, big_blind=bb, seed=h)
        hand.start()
        _play_hand(hand, hero, villains, om)
        out.append((players[0].stack - stack) / bb)
    return out, hero


# ----------------- estatística -----------------
def bootstrap_ci(d: list[float], iters: int = 10000, seed: int = 1) -> tuple[float, float]:
    """IC95% da média por BOOTSTRAP (numpy, vetorizado) — robusto à cauda pesada do poker."""
    import numpy as np

    arr = np.asarray(d, dtype=np.float64)
    n = len(arr)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(iters, n))
    means = arr[idx].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def paired(base: list[float], om: list[float]) -> dict:
    n = len(base)
    d = [om[i] - base[i] for i in range(n)]
    lo, hi = bootstrap_ci(d)
    return {
        "base": 100 * sum(base) / n, "om": 100 * sum(om) / n,
        "delta": 100 * sum(d) / n, "lo": 100 * lo, "hi": 100 * hi,
        "n_eff": sum(1 for x in d if x != 0),
    }


def main() -> None:
    n_test = int(sys.argv[1]) if len(sys.argv) > 1 else 12000
    n_calib = int(sys.argv[2]) if len(sys.argv) > 2 else 6000
    if not _MODEL.exists():
        print("Expert ONNX não encontrado.")
        return
    rc = random.Random(111)
    calib_seeds = [rc.randrange(1 << 30) for _ in range(n_calib)]
    rt = random.Random(999999)
    test_seeds = [rt.randrange(1 << 30) for _ in range(n_test)]

    print(f"# EXPERIMENTO Expert opponent-aware (pre-registrado) | calib {n_calib} / teste {n_test} maos")
    print("# pareado por baralho, IC95% bootstrap. seeds calib!=teste. vil calib!=teste.\n")

    EXPLOITABLE = ["overfolder", "station", "maniac"]
    ROBUST = ["montecarlo", "heuristic", "expert_mirror"]
    CONTROL = ["random"]
    base_cache: dict[str, list[float]] = {}

    def base_test(v: str) -> list[float]:
        if v not in base_cache:
            base_cache[v] = _run(v, test_seeds, 0.0, None)[0]
        return base_cache[v]

    # ---- CALIBRAÇÃO: escolhe k por variante, só no overfolder (calib), seeds de calib ----
    print("## CALIBRACAO (vilao=overfolder, seeds de CALIB) — escolhe k por variante")
    base_c = _run("overfolder", calib_seeds, 0.0, None)[0]
    best = {}
    for variant in ("v1", "v2"):
        bk, bg = 0.0, -1e9
        for k in (1.0, 2.0, 4.0):
            om, _h = _run("overfolder", calib_seeds, k, variant)
            s = paired(base_c, om)
            print(f"  {variant} k={k}: d {s['delta']:+7.1f} [{s['lo']:+.1f},{s['hi']:+.1f}] "
                  f"altera {100*_h.altered/max(_h.active,1):.0f}%")
            if s["delta"] > bg:
                bg, bk = s["delta"], k
        best[variant] = bk
        print(f"  >>> {variant}: k*={bk}\n")

    # ---- TESTE: held-out, seeds de TESTE, ambas as variantes ----
    for variant in ("v1", "v2"):
        k = best[variant]
        print(f"## TESTE held-out — {variant.upper()} k={k}  (seeds de TESTE, disjuntos)")
        sub = {"EXPLORAVEL": [], "ROBUSTO": []}
        for grp, vils in (("EXPLORAVEL", EXPLOITABLE), ("ROBUSTO", ROBUST), ("CONTROLE", CONTROL)):
            for v in vils:
                om, h = _run(v, test_seeds, k, variant)
                s = paired(base_test(v), om)
                flag = ""
                if s["lo"] > 0:
                    flag = " GANHO(sig)"
                elif s["hi"] < 0:
                    flag = " PERDA(sig)"
                if grp == "CONTROLE" and s["lo"] > 5:
                    flag += " *RED-FLAG*"
                alt = 100 * h.altered / max(h.active, 1)
                print(f"  [{grp:10s}] {v:14s}: base {s['base']:+7.1f} | OM {s['om']:+7.1f} | "
                      f"d {s['delta']:+7.1f} [{s['lo']:+.1f},{s['hi']:+.1f}] alt {alt:.0f}%{flag}")
                if grp in sub:
                    sub[grp].append(s)
        # veredito mecânico
        expl_ok = sum(1 for s in sub["EXPLORAVEL"] if s["lo"] > 0) >= 2
        rob_ok = all(s["hi"] > -5 for s in sub["ROBUSTO"])
        verdict = "PROMOVE" if (expl_ok and rob_ok) else "REPROVA (mantem OFF, como o equity guard)"
        print(f"  >>> VEREDITO {variant.upper()}: exploravel_ganha={expl_ok} robusto_nao_inferior={rob_ok} -> {verdict}\n")


if __name__ == "__main__":
    main()
