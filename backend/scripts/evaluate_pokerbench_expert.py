"""Evaluate one governed Expert v2 candidate on immutable PokerBench test CSVs."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from poker_arena.bots.ml_bot import EvaluationMLBot
from poker_arena.ml.pokerbench_eval import evaluate_pokerbench_csv
from poker_arena.ml.promotion_contract import promotion_contract_sha256
from poker_arena.model_artifacts import verify_evaluation_candidate


def _sha(value: str) -> str:
    normalized = value.lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise argparse.ArgumentTypeError("expected a lowercase/uppercase SHA-256 digest")
    return normalized


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--preflop-csv", type=Path, required=True)
    parser.add_argument("--preflop-sha256", type=_sha, required=True)
    parser.add_argument("--postflop-csv", type=Path, required=True)
    parser.add_argument("--postflop-sha256", type=_sha, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    artifact = verify_evaluation_candidate(args.model, "expert", manifest_path=args.manifest)
    bot = EvaluationMLBot(args.model, manifest_path=args.manifest, seed=0)
    preflop = evaluate_pokerbench_csv(
        args.preflop_csv,
        expected_sha256=args.preflop_sha256,
        predictor=bot.policy_distribution,
    )
    postflop = evaluate_pokerbench_csv(
        args.postflop_csv,
        expected_sha256=args.postflop_sha256,
        predictor=bot.policy_distribution,
    )
    receipt = {
        "schema_version": 1,
        "profile_revision": "poker-arena-pokerbench-v2-eval-2026-08-08",
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "artifact_sha256": artifact.sha256,
        "artifact_contract_sha256": promotion_contract_sha256(artifact.entry),
        "datasets": {
            "preflop": {"sha256": args.preflop_sha256, "metrics": asdict(preflop)},
            "postflop": {"sha256": args.postflop_sha256, "metrics": asdict(postflop)},
        },
        "interpretation": (
            "Solver-label agreement is secondary evidence; it is not EV, exploitability, "
            "mixed-strategy fidelity, or proof of professional strength."
        ),
    }
    payload = json.dumps(
        receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(payload + "\n")
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
