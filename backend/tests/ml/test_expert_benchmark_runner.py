from __future__ import annotations

import inspect

import pytest

from poker_arena.bots.random_bot import RandomBot
from poker_arena.ml.expert_benchmark import BenchmarkCell
from poker_arena.ml.expert_benchmark_runner import (
    _run_paired_block,
    run_preregistered_benchmark,
)


def test_paired_block_is_reproducible_and_binds_transcripts():
    cell = BenchmarkCell("beginner", "random", 2, 20)
    factory = lambda seed: RandomBot(seed=seed)  # noqa: E731
    first = _run_paired_block(
        cell,
        candidate_factory=factory,
        baseline_factory=factory,
        block_index=0,
        hands=2,
        execution_binding="a" * 64,
    )
    second = _run_paired_block(
        cell,
        candidate_factory=factory,
        baseline_factory=factory,
        block_index=0,
        hands=2,
        execution_binding="a" * 64,
    )
    assert first == second
    assert first["candidate_chips_delta"] == first["baseline_chips_delta"]
    assert first["candidate_transcript_sha256"] == first["baseline_transcript_sha256"]
    assert len(str(first["id"])) == 64


def test_official_runner_refuses_reduced_smoke_volume():
    with pytest.raises(ValueError, match="cannot be reduced"):
        run_preregistered_benchmark(
            candidate_model_path="missing.onnx",
            candidate_manifest_path="missing.json",
            hands_per_block=1,
            blocks_per_cell=1,
        )


def test_official_runner_exposes_no_factory_or_identity_substitution_hooks():
    parameters = set(inspect.signature(run_preregistered_benchmark).parameters)
    assert parameters == {
        "candidate_model_path",
        "candidate_manifest_path",
        "hands_per_block",
        "blocks_per_cell",
    }
