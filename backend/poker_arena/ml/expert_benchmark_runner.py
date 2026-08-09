"""Deterministic paired cross-play runner for Expert promotion evidence."""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from poker_arena.bots.base import Bot
from poker_arena.bots.ml_bot import EvaluationMLBot
from poker_arena.bots.observation import observation_for
from poker_arena.engine.game import Hand
from poker_arena.engine.player import Player, PlayerStatus
from poker_arena.ml.benchmark_opponents import (
    baseline_policy_sha256,
    create_benchmark_baseline,
    create_benchmark_opponent,
)
from poker_arena.ml.expert_benchmark import (
    ACTION_COUNT_KEYS,
    MIN_BLOCKS_PER_CELL,
    MIN_HANDS_PER_BLOCK,
    RAW_RESULTS_PROFILE_REVISION,
    BenchmarkCell,
    _block_identity,
    balanced_hands_per_block,
    current_execution_binding,
    execution_binding_sha256,
    preregistered_cells,
)
from poker_arena.ml.promotion_contract import promotion_contract_sha256
from poker_arena.model_artifacts import (
    revalidate_model_artifact_identity,
    verify_evaluation_candidate,
)

PolicyFactory = Callable[[int], Bot]
_MAX_TRANSITIONS = 500


def _derived_seed(*values: object) -> int:
    payload = ":".join(str(value) for value in values).encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _play_hand(
    hero: Bot,
    *,
    opponent_name: str,
    table_size: int,
    stack: int,
    hero_seat: int,
    button: int,
    deal_seed: int,
    opponent_seed: int,
) -> tuple[int, int, str, dict[str, int]]:
    players = [Player(f"P{seat}", stack) for seat in range(table_size)]
    hand = Hand(players, button=button, small_blind=10, big_blind=20, seed=deal_seed)
    opponents = {
        seat: create_benchmark_opponent(opponent_name, _derived_seed(opponent_seed, seat))
        for seat in range(table_size)
        if seat != hero_seat
    }
    hand.start()
    decisions = 0
    action_counts = dict.fromkeys(ACTION_COUNT_KEYS, 0)
    transitions = 0
    while transitions < _MAX_TRANSITIONS:
        while not hand.round_complete():
            transitions += 1
            if transitions >= _MAX_TRANSITIONS:
                raise RuntimeError("benchmark hand exceeded the transition limit")
            seat = hand.to_act
            observation = observation_for(hand)
            if seat == hero_seat:
                action = hero.act(observation)
                decisions += 1
                action_counts[action.type.value] += 1
            else:
                action = opponents[seat].act(observation)
            if action.type not in observation.legal_actions:
                raise RuntimeError("benchmark policy emitted an illegal action")
            hand.apply(action)
        live = [player for player in players if player.status != PlayerStatus.FOLDED]
        if len(live) <= 1 or len(hand.board) >= 5:
            hand.resolve()
            transcript = {
                "deal_seed": deal_seed,
                "button": button,
                "hero_seat": hero_seat,
                "board": [str(card) for card in hand.board],
                "events": [asdict(event) for event in hand.public_history],
                "final_stacks": [player.stack for player in players],
            }
            payload = json.dumps(
                transcript,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode()
            return (
                players[hero_seat].stack - stack,
                decisions,
                hashlib.sha256(payload).hexdigest(),
                action_counts,
            )
        hand.advance_street()
    raise RuntimeError("benchmark hand did not terminate")


def _run_paired_block(
    cell: BenchmarkCell,
    *,
    candidate_factory: PolicyFactory,
    baseline_factory: PolicyFactory,
    block_index: int,
    hands: int,
    execution_binding: str,
) -> dict[str, object]:
    """Run candidate and baseline on the same deals and rotated hero seats."""

    if type(block_index) is not int or block_index < 0:
        raise ValueError("block_index must be a non-negative int")
    if type(hands) is not int or hands <= 0:
        raise ValueError("hands must be a positive int")
    deal_seed = _derived_seed(cell.identifier, block_index, "deals")
    candidate_seed = _derived_seed(cell.identifier, block_index, "candidate")
    baseline_seed = _derived_seed(cell.identifier, block_index, "baseline")
    candidate = candidate_factory(candidate_seed)
    baseline = baseline_factory(baseline_seed)
    candidate_delta = baseline_delta = 0
    candidate_decisions = baseline_decisions = 0
    candidate_action_counts = dict.fromkeys(ACTION_COUNT_KEYS, 0)
    baseline_action_counts = dict.fromkeys(ACTION_COUNT_KEYS, 0)
    candidate_transcripts = hashlib.sha256()
    baseline_transcripts = hashlib.sha256()
    rng = random.Random(deal_seed)  # noqa: S311 - deterministic scientific simulation
    stack = cell.stack_depth_bb * 20
    for hand_index in range(hands):
        hand_seed = rng.randrange(1 << 63)
        hero_seat = hand_index % cell.table_size
        button = (hand_index // cell.table_size) % cell.table_size
        opponent_seed = _derived_seed(cell.identifier, block_index, hand_index, "opponents")
        delta, count, transcript, action_counts = _play_hand(
            candidate,
            opponent_name=cell.opponent,
            table_size=cell.table_size,
            stack=stack,
            hero_seat=hero_seat,
            button=button,
            deal_seed=hand_seed,
            opponent_seed=opponent_seed,
        )
        candidate_delta += delta
        candidate_decisions += count
        for action_type in ACTION_COUNT_KEYS:
            candidate_action_counts[action_type] += action_counts[action_type]
        candidate_transcripts.update(bytes.fromhex(transcript))
        delta, count, transcript, action_counts = _play_hand(
            baseline,
            opponent_name=cell.opponent,
            table_size=cell.table_size,
            stack=stack,
            hero_seat=hero_seat,
            button=button,
            deal_seed=hand_seed,
            opponent_seed=opponent_seed,
        )
        baseline_delta += delta
        baseline_decisions += count
        for action_type in ACTION_COUNT_KEYS:
            baseline_action_counts[action_type] += action_counts[action_type]
        baseline_transcripts.update(bytes.fromhex(transcript))
    # Reaching this point proves the strict evaluator emitted no non-finite output
    # or fallback and that every emitted action passed the engine legality check.
    block: dict[str, object] = {
        "id": "0" * 64,
        "deal_seed": deal_seed,
        "candidate_policy_seed": candidate_seed,
        "baseline_policy_seed": baseline_seed,
        "hands": hands,
        "candidate_chips_delta": candidate_delta,
        "baseline_chips_delta": baseline_delta,
        "big_blind": 20,
        "decisions": candidate_decisions + baseline_decisions,
        "candidate_decisions": candidate_decisions,
        "baseline_decisions": baseline_decisions,
        "candidate_action_counts": candidate_action_counts,
        "baseline_action_counts": baseline_action_counts,
        "illegal_actions": 0,
        "non_finite_outputs": 0,
        "fallbacks": 0,
        "execution_binding_sha256": execution_binding,
        "candidate_transcript_sha256": candidate_transcripts.hexdigest(),
        "baseline_transcript_sha256": baseline_transcripts.hexdigest(),
    }
    block["id"] = _block_identity(cell, block)
    return block


def run_preregistered_benchmark(
    *,
    candidate_model_path: str | Path,
    candidate_manifest_path: str | Path,
    hands_per_block: int = MIN_HANDS_PER_BLOCK,
    blocks_per_cell: int = MIN_BLOCKS_PER_CELL,
) -> dict[str, object]:
    """Execute the frozen panel with identities derived from verified objects.

    The caller cannot supply factories, hashes or a decision rule.  The official
    runner verifies and instantiates the strict ONNX candidate itself and creates
    the versioned baseline internally, preventing evaluation/deploy substitution.
    """

    if hands_per_block < MIN_HANDS_PER_BLOCK or blocks_per_cell < MIN_BLOCKS_PER_CELL:
        raise ValueError("official benchmark volume cannot be reduced")
    artifact = verify_evaluation_candidate(
        candidate_model_path,
        "expert",
        manifest_path=candidate_manifest_path,
    )
    candidate_contract_sha256 = promotion_contract_sha256(artifact.entry)
    baseline_sha256 = baseline_policy_sha256()
    decision_rule = artifact.inference_policy.decision_rule

    def candidate_factory(seed: int) -> Bot:
        return EvaluationMLBot(
            artifact.path,
            manifest_path=artifact.manifest_path,
            seed=seed,
            equity_guard=False,
        )

    execution: dict[str, object] = {
        "candidate_artifact_sha256": artifact.sha256,
        "candidate_manifest_sha256": artifact.manifest_sha256,
        "candidate_contract_sha256": candidate_contract_sha256,
        "baseline_policy_sha256": baseline_sha256,
        "decision_rule": decision_rule,
        **current_execution_binding(),
        "binding_sha256": "0" * 64,
    }
    execution["binding_sha256"] = execution_binding_sha256(execution)
    cells = []
    for cell in preregistered_cells():
        balanced_hands = balanced_hands_per_block(hands_per_block, cell.table_size)
        blocks = [
            _run_paired_block(
                cell,
                candidate_factory=candidate_factory,
                baseline_factory=create_benchmark_baseline,
                block_index=index,
                hands=balanced_hands,
                execution_binding=str(execution["binding_sha256"]),
            )
            for index in range(blocks_per_cell)
        ]
        cells.append(
            {
                "level": cell.level,
                "opponent": cell.opponent,
                "table_size": cell.table_size,
                "stack_depth_bb": cell.stack_depth_bb,
                "blocks": blocks,
            }
        )
    revalidate_model_artifact_identity(artifact)
    return {
        "schema_version": 1,
        "profile_revision": RAW_RESULTS_PROFILE_REVISION,
        "execution": execution,
        "cells": cells,
    }
