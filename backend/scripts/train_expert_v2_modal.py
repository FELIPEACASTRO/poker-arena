"""Bounded Modal L4 warm-start for the Poker Arena Expert v2 candidate."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
from pathlib import Path

import modal

RUN_ID = os.environ.get("POKER_MODAL_RUN_ID", "unconfigured")
GIT_COMMIT = os.environ.get("POKER_GIT_COMMIT", "unconfigured")
SOURCE_BINDING = os.environ.get("POKER_SOURCE_BINDING", "unconfigured")
CLASS_WEIGHT_PROFILE = os.environ.get("POKER_CLASS_WEIGHT_PROFILE", "unconfigured")
HYPOTHESIS_ID = os.environ.get("POKER_HYPOTHESIS_ID", "unconfigured")
PURPOSE = "expert-v2-weight-calibration-ablation"
MAX_ESTIMATED_USD = "0.60"
EXPECTED_MODAL_ENVIRONMENT = "poker-arena"
WEIGHT_HYPOTHESES = {
    "uniform": "H-WEIGHT-UNIFORM-CONTROL-V1",
    "inverse_sqrt_cap5": "H-WEIGHT-INVSQRT-CAP5-V1",
}
TRAINING_SEEDS = (1701, 2903, 4157)
MAX_EPOCHS = 24
MIN_EPOCHS = 8
EARLY_STOPPING_PATIENCE = 4
EARLY_STOPPING_MIN_DELTA = 1e-4
BATCH_SIZE = 8_192
EVALUATION_BATCH_SIZE = 16_384
LEARNING_RATE = 2e-3
WEIGHT_DECAY = 1e-4
GRADIENT_CLIP_NORM = 5.0
CALIBRATION_TEMPERATURE_MIN = 0.05
CALIBRATION_TEMPERATURE_MAX = 20.0
ONNX_PARITY_MAX_ABS_ERROR = 1e-4


def _resolve_backend_root(script_path: Path) -> Path:
    """Resolve both checkout ``backend/scripts`` and Modal ``/root`` layouts."""

    resolved = script_path.resolve()
    for candidate in (resolved.parent.parent, resolved.parent):
        if (candidate / "poker_arena" / "ml" / "expert_training_v2.py").is_file() and (
            candidate / "uv.lock"
        ).is_file():
            return candidate
    raise FileNotFoundError("backend root lacks poker_arena/ml/expert_training_v2.py or uv.lock")


BACKEND_ROOT = _resolve_backend_root(Path(__file__))


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _package_source_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py"), key=lambda value: value.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        file_digest = hashlib.sha256(path.read_bytes()).digest()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(file_digest)
    return digest.hexdigest()


def _candidate_destination(output_dir: str, *, backend_root: Path, run_id: str) -> Path:
    destination = Path(output_dir).resolve()
    expected = (backend_root / "models" / "candidates" / run_id).resolve()
    if destination != expected:
        raise ValueError(f"candidate output must be exactly {expected}")
    return destination


def _verify_remote_result(result: object, *, run_id: str, source_binding: str) -> None:
    if not isinstance(result, dict):
        raise RuntimeError("remote candidate result must be a mapping")
    metadata = result.get("metadata")
    if not isinstance(metadata, dict):
        raise RuntimeError("remote candidate metadata is absent")
    if metadata.get("run_id") != run_id or metadata.get("source_binding") != source_binding:
        raise RuntimeError("remote candidate identity differs from the launched run")
    expected = metadata.get("artifact_sha256")
    if not isinstance(expected, dict):
        raise RuntimeError("remote candidate artifact digests are absent")
    payloads = {
        "onnx": result.get("onnx"),
        "checkpoint": result.get("checkpoint"),
        "training_trace": result.get("training_trace"),
        "inference_trace_gzip": result.get("inference_trace_gzip"),
    }
    for name, payload in payloads.items():
        if not isinstance(payload, bytes):
            raise RuntimeError(f"remote candidate payload {name!r} is not bytes")
        if hashlib.sha256(payload).hexdigest() != expected.get(name):
            raise RuntimeError(f"remote candidate payload {name!r} failed digest verification")


PACKAGE_SOURCE_SHA256 = _package_source_sha256(BACKEND_ROOT / "poker_arena")
TRAINER_SHA256 = _sha256_file(Path(__file__).resolve())
TRAINING_MODULE_SHA256 = _sha256_file(BACKEND_ROOT / "poker_arena" / "ml" / "expert_training_v2.py")
DEPENDENCY_LOCK_SHA256 = _sha256_file(BACKEND_ROOT / "uv.lock")
CALCULATED_SOURCE_BINDING = hashlib.sha256(
    "|".join(
        (
            PACKAGE_SOURCE_SHA256,
            TRAINER_SHA256,
            TRAINING_MODULE_SHA256,
            DEPENDENCY_LOCK_SHA256,
        )
    ).encode("ascii")
).hexdigest()

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "numpy==2.4.6",
        "torch==2.8.0",
        "onnx==1.22.0",
        "onnxruntime==1.27.0",
        "treys==0.1.8",
    )
    .env(
        {
            "CUBLAS_WORKSPACE_CONFIG": ":4096:8",
            "PYTHONPATH": "/root",
            "POKER_MODAL_RUN_ID": RUN_ID,
            "POKER_GIT_COMMIT": GIT_COMMIT,
            "POKER_SOURCE_BINDING": SOURCE_BINDING,
            "POKER_CLASS_WEIGHT_PROFILE": CLASS_WEIGHT_PROFILE,
            "POKER_HYPOTHESIS_ID": HYPOTHESIS_ID,
        }
    )
    .add_local_dir(BACKEND_ROOT / "poker_arena", "/root/poker_arena", copy=True)
    .add_local_file(BACKEND_ROOT / "uv.lock", "/root/uv.lock", copy=True)
    .run_commands(
        'python -c "import os, re; '
        "from importlib.metadata import version; "
        "from poker_arena.ml.expert_training_v2 import COMPRESSED_FEATURES; "
        "assert COMPRESSED_FEATURES == 740; "
        "assert version('numpy') == '2.4.6'; "
        "assert version('torch') == '2.8.0'; "
        "assert version('onnx') == '1.22.0'; "
        "assert version('onnxruntime') == '1.27.0'; "
        "assert version('treys') == '0.1.8'; "
        "assert re.fullmatch(r'poker-expert-v2-[0-9]{8}t[0-9]{6}z-[0-9a-f]{8}', "
        "os.environ['POKER_MODAL_RUN_ID']); "
        "assert re.fullmatch(r'[0-9a-f]{40}', os.environ['POKER_GIT_COMMIT']); "
        "assert re.fullmatch(r'[0-9a-f]{64}', os.environ['POKER_SOURCE_BINDING'])\""
    )
    .run_commands(
        'python -c "import hashlib; from pathlib import Path; '
        f"assert Path('/root/uv.lock').is_file(); "
        f"assert Path('/root/poker_arena/ml/expert_training_v2.py').is_file(); "
        f"assert hashlib.sha256(Path('/root/uv.lock').read_bytes()).hexdigest() == "
        f"'{DEPENDENCY_LOCK_SHA256}'; "
        f"assert hashlib.sha256(Path('/root/poker_arena/ml/expert_training_v2.py').read_bytes()).hexdigest() == "
        f"'{TRAINING_MODULE_SHA256}'\""
    )
)
app = modal.App(
    f"poker-arena-expert-v2-{RUN_ID}",
    tags={
        "project": "POKER",
        "owner": "codex",
        "run_id": RUN_ID,
        "purpose": PURPOSE,
        "max_estimated_usd": MAX_ESTIMATED_USD,
        # Modal allows at most eight tags. The full commit is retained in the
        # hash-bound lifecycle receipt and remote metadata instead.
        "source_binding": SOURCE_BINDING[:32],
        "class_weight_profile": CLASS_WEIGHT_PROFILE,
        "hypothesis_id": HYPOTHESIS_ID,
    },
)


@app.function(
    image=image,
    gpu="L4",
    cpu=4.0,
    memory=16_384,
    timeout=1_800,
    retries=0,
    single_use_containers=True,
)
def train() -> dict[str, object]:
    import gzip
    import hashlib
    import math
    import subprocess
    import sys
    import tempfile
    import time
    import urllib.request

    import numpy as np
    import onnxruntime as ort
    import torch
    from torch import nn

    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True

    from poker_arena.ml.encoder_v2 import (
        CARD_FEATURES,
        GLOBAL_FEATURES,
        HISTORY_FEATURES,
        MAX_HISTORY,
        MAX_SEATS,
        SEAT_FEATURES,
    )
    from poker_arena.ml.expert_training_v2 import (
        COMPRESSED_FEATURES,
        MAX_INVERSE_SQRT_WEIGHT,
        POKERBENCH_FILES,
        STATIC_STATE_FEATURES,
        class_weights_for_profile,
        decontaminated_split,
        group_label_audit,
        multiclass_probability_diagnostics,
        prepare_csv_files,
        sealed_final_holdout_member,
    )

    if (
        RUN_ID == "unconfigured"
        or re.fullmatch(r"poker-expert-v2-[0-9]{8}t[0-9]{6}z-[0-9a-f]{8}", RUN_ID) is None
        or re.fullmatch(r"[0-9a-f]{40}", GIT_COMMIT) is None
        or re.fullmatch(r"[0-9a-f]{64}", SOURCE_BINDING) is None
        or SOURCE_BINDING != CALCULATED_SOURCE_BINDING
        or WEIGHT_HYPOTHESES.get(CLASS_WEIGHT_PROFILE) != HYPOTHESIS_ID
    ):
        raise RuntimeError("run identity/source binding is absent or malformed")
    remote_package = Path("/root/poker_arena")
    if _package_source_sha256(remote_package) != PACKAGE_SOURCE_SHA256:
        raise RuntimeError("remote package source differs from the bound local package")
    if _sha256_file(remote_package / "ml" / "expert_training_v2.py") != TRAINING_MODULE_SHA256:
        raise RuntimeError("remote training module differs from the bound source")
    if os.environ.get("MODAL_ENVIRONMENT") != EXPECTED_MODAL_ENVIRONMENT:
        raise RuntimeError("Modal environment isolation contract was not met")
    started = time.perf_counter()
    download_started = time.perf_counter()
    base = "https://huggingface.co/datasets/RZ412/PokerBench/resolve/main/"
    temporary_directory = tempfile.TemporaryDirectory(prefix=f"poker-arena-{RUN_ID}-")
    root = Path(temporary_directory.name)
    paths: dict[str, Path] = {}
    for key, (filename, expected_sha) in POKERBENCH_FILES.items():
        path = root / filename
        urllib.request.urlretrieve(  # noqa: S310 - pinned by SHA-256
            base + filename,
            path,
        )
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected_sha:
            raise RuntimeError(f"dataset digest mismatch for {key}")
        paths[key] = path

    download_elapsed_seconds = time.perf_counter() - download_started
    preparation_started = time.perf_counter()
    train_data = prepare_csv_files(
        [
            ("preflop_train", paths["preflop_train"]),
            ("postflop_train", paths["postflop_train"]),
        ],
        redact_split_member=sealed_final_holdout_member,
    )
    test_inputs = prepare_csv_files(
        [
            ("preflop_test", paths["preflop_test"]),
            ("postflop_test", paths["postflop_test"]),
        ],
        redact_split_member=lambda _split_id: True,
    )
    preparation_elapsed_seconds = time.perf_counter() - preparation_started
    for dataset_name, dataset in (("train", train_data), ("published_test", test_inputs)):
        if dataset.parse_failures:
            raise RuntimeError(
                f"{dataset_name} PokerBench parser rejected {dataset.parse_failures} rows"
            )
        if dataset.history_audit[:, 4].any() or not np.array_equal(
            dataset.history_audit[:, 1], dataset.history_audit[:, 2]
        ):
            raise RuntimeError(f"{dataset_name} PokerBench history fidelity gate failed")
    if not np.all(test_inputs.targets == -1):
        raise RuntimeError("published test labels were consulted before candidate selection")
    split = decontaminated_split(
        train_data.split_ids,
        train_data.group_ids,
        test_inputs.group_ids,
    )
    training_mask = split.training_mask
    validation_mask = split.validation_mask
    calibration_mask = split.calibration_mask
    calibration_check_mask = split.calibration_check_mask
    sealed_final_holdout_mask = split.sealed_final_holdout_mask
    train_test_overlap_examples_excluded = split.overlap_example_count
    train_test_overlap_groups_excluded = split.overlap_group_count
    test_groups = set(test_inputs.group_ids.tolist())
    training_groups = set(train_data.group_ids[training_mask].tolist())
    validation_groups = set(train_data.group_ids[validation_mask].tolist())
    calibration_groups = set(train_data.group_ids[calibration_mask].tolist())
    calibration_check_groups = set(train_data.group_ids[calibration_check_mask].tolist())
    sealed_final_holdout_groups = set(train_data.group_ids[sealed_final_holdout_mask].tolist())
    sealed_final_holdout_split_ids = set(train_data.split_ids[sealed_final_holdout_mask].tolist())
    if (
        training_groups & validation_groups
        or training_groups & calibration_groups
        or training_groups & calibration_check_groups
        or validation_groups & calibration_groups
        or validation_groups & calibration_check_groups
        or calibration_groups & calibration_check_groups
    ):
        raise RuntimeError("state-group leakage crossed a development boundary")
    if (
        training_groups & sealed_final_holdout_groups
        or validation_groups & sealed_final_holdout_groups
        or calibration_groups & sealed_final_holdout_groups
        or calibration_check_groups & sealed_final_holdout_groups
    ):
        raise RuntimeError("sealed final holdout crossed a development boundary")
    train_test_group_overlap = len(
        (
            training_groups
            | validation_groups
            | calibration_groups
            | calibration_check_groups
            | sealed_final_holdout_groups
        )
        & test_groups
    )
    if train_test_group_overlap:
        raise RuntimeError("published test decontamination did not remove every exact overlap")

    device = torch.device("cuda")
    if not torch.cuda.is_available():
        raise RuntimeError("L4 allocation did not expose CUDA")
    gpu_name = torch.cuda.get_device_name(0)
    total_vram = torch.cuda.get_device_properties(0).total_memory
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True

    def gpu_snapshot() -> dict[str, object]:
        command = [
            "nvidia-smi",
            "--query-gpu=name,uuid,temperature.gpu,power.draw,power.limit,utilization.gpu,"
            "memory.used,memory.total,clocks.sm,clocks.mem",
            "--format=csv,noheader,nounits",
        ]
        observed = subprocess.run(  # noqa: S603,S607 - fixed NVIDIA diagnostic command
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        fields = [field.strip() for field in observed.split(",")]
        if len(fields) != 10:
            raise RuntimeError("nvidia-smi diagnostic contract changed")
        return {
            "name": fields[0],
            "uuid": fields[1],
            "temperature_c": float(fields[2]),
            "power_draw_w": float(fields[3]),
            "power_limit_w": float(fields[4]),
            "utilization_percent": float(fields[5]),
            "memory_used_mib": float(fields[6]),
            "memory_total_mib": float(fields[7]),
            "sm_clock_mhz": float(fields[8]),
            "memory_clock_mhz": float(fields[9]),
        }

    x_train = torch.from_numpy(train_data.features[training_mask]).to(device)
    y_train = torch.from_numpy(train_data.targets[training_mask]).to(device)
    x_val = torch.from_numpy(train_data.features[validation_mask]).to(device)
    y_val = torch.from_numpy(train_data.targets[validation_mask]).to(device)
    x_calibration = torch.from_numpy(train_data.features[calibration_mask]).to(device)
    y_calibration = torch.from_numpy(train_data.targets[calibration_mask]).to(device)
    x_calibration_check = torch.from_numpy(train_data.features[calibration_check_mask]).to(device)
    y_calibration_check = torch.from_numpy(train_data.targets[calibration_check_mask]).to(device)
    label_consistency = {
        "training": group_label_audit(
            train_data.group_ids[training_mask], train_data.targets[training_mask]
        ),
        "validation": group_label_audit(
            train_data.group_ids[validation_mask], train_data.targets[validation_mask]
        ),
        "calibration": group_label_audit(
            train_data.group_ids[calibration_mask], train_data.targets[calibration_mask]
        ),
        "calibration_check": group_label_audit(
            train_data.group_ids[calibration_check_mask],
            train_data.targets[calibration_check_mask],
        ),
    }
    if not np.all(train_data.targets[sealed_final_holdout_mask] == -1):
        raise RuntimeError("sealed final holdout labels were consulted before partitioning")
    development_masks = training_mask | validation_mask | calibration_mask | calibration_check_mask
    if np.any(train_data.targets[development_masks] < 0):
        raise RuntimeError("a development partition contains a redacted target")

    class Core(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.static = nn.Sequential(
                nn.Linear(STATIC_STATE_FEATURES + 10, 192),
                nn.GELU(),
                nn.LayerNorm(192),
            )
            self.history = nn.GRU(
                input_size=HISTORY_FEATURES,
                hidden_size=64,
                batch_first=True,
            )
            self.head = nn.Sequential(
                nn.Linear(192 + 64, 128),
                nn.GELU(),
                nn.LayerNorm(128),
                nn.Linear(128, 10),
            )

        def forward(self, features: torch.Tensor) -> torch.Tensor:
            history_start = STATIC_STATE_FEATURES
            history_end = history_start + MAX_HISTORY * HISTORY_FEATURES
            static_features = torch.cat(
                (features[:, :history_start], features[:, history_end:]), dim=1
            )
            history = features[:, history_start:history_end].reshape(
                -1, MAX_HISTORY, HISTORY_FEATURES
            )
            history_mask = history.abs().sum(dim=2) > 0.0
            history_output, _hidden = self.history(history)
            last_event = history_mask.sum(dim=1).long().sub(1).clamp(min=0)
            batch_indexes = torch.arange(features.shape[0], device=features.device)
            history_summary = history_output[batch_indexes, last_event]
            history_summary = history_summary * history_mask.any(dim=1, keepdim=True)
            return self.head(torch.cat((self.static(static_features), history_summary), dim=1))

    def masked_logits(model: nn.Module, features: torch.Tensor) -> torch.Tensor:
        logits = model(features)
        return logits.masked_fill(features[:, -10:] < 0.5, -1e9)

    counts = torch.bincount(y_train, minlength=10)
    weights = torch.from_numpy(
        class_weights_for_profile(counts.cpu().numpy(), CLASS_WEIGHT_PROFILE)
    ).to(device=device, dtype=torch.float32)
    if CLASS_WEIGHT_PROFILE == "uniform":
        weight_scheme = "uniform_control"
        maximum_weight: float | None = None
    elif CLASS_WEIGHT_PROFILE == "inverse_sqrt_cap5":
        weight_scheme = "inverse_square_root_frequency"
        maximum_weight = MAX_INVERSE_SQRT_WEIGHT
    else:
        raise RuntimeError("class-weight profile is not preregistered")
    criterion = nn.CrossEntropyLoss(weight=weights)
    weighted_class_mass = counts.float() * weights

    def metrics(
        model: nn.Module,
        features: torch.Tensor,
        targets: torch.Tensor,
        *,
        temperature: float = 1.0,
    ) -> dict[str, float]:
        if not math.isfinite(temperature) or temperature <= 0:
            raise RuntimeError("probability temperature must be finite and positive")
        model.eval()
        losses = []
        correct = top3 = total = 0
        nontrivial_top3_correct = nontrivial_top3_total = 0
        with torch.inference_mode():
            for start_index in range(0, len(targets), EVALUATION_BATCH_SIZE):
                xb = features[start_index : start_index + EVALUATION_BATCH_SIZE]
                yb = targets[start_index : start_index + EVALUATION_BATCH_SIZE]
                logits = masked_logits(model, xb) / temperature
                losses.append(float(nn.functional.cross_entropy(logits, yb).item()) * len(yb))
                correct += int((logits.argmax(1) == yb).sum().item())
                top3_hits = (logits.topk(3, dim=1).indices == yb[:, None]).any(1)
                top3 += int(top3_hits.sum().item())
                nontrivial = xb[:, -10:].sum(dim=1) > 3.0
                nontrivial_top3_correct += int((top3_hits & nontrivial).sum().item())
                nontrivial_top3_total += int(nontrivial.sum().item())
                total += len(yb)
        return {
            "loss": sum(losses) / total,
            "accuracy": correct / total,
            "top3": top3 / total,
            "top3_nontrivial": (
                nontrivial_top3_correct / nontrivial_top3_total if nontrivial_top3_total else 0.0
            ),
            "top3_nontrivial_examples": float(nontrivial_top3_total),
            "top3_tautological_fraction": (total - nontrivial_top3_total) / total,
        }

    trace_events: list[dict[str, object]] = [
        {
            "event": "training_configuration",
            "run_id": RUN_ID,
            "git_commit": GIT_COMMIT,
            "source_binding": SOURCE_BINDING,
            "release_status": "candidate_only_not_promoted",
            "model": {
                "static_input": STATIC_STATE_FEATURES + 10,
                "static_hidden": 192,
                "history_encoder": "causal_gru_shared_weights",
                "history_shape": [MAX_HISTORY, HISTORY_FEATURES],
                "history_hidden": 64,
                "head_hidden": 128,
                "actions": 10,
                "compressed_input": COMPRESSED_FEATURES,
            },
            "activation": "GELU",
            "normalization": "LayerNorm",
            "optimizer": "AdamW",
            "learning_rate": LEARNING_RATE,
            "weight_decay": WEIGHT_DECAY,
            "weight_decay_policy": "ndim_ge_2_only; biases_and_norm_parameters_zero_decay",
            "max_epochs": MAX_EPOCHS,
            "min_epochs": MIN_EPOCHS,
            "early_stopping_patience": EARLY_STOPPING_PATIENCE,
            "early_stopping_min_validation_nll_delta": EARLY_STOPPING_MIN_DELTA,
            "batch_size": BATCH_SIZE,
            "gradient_clip_norm": GRADIENT_CLIP_NORM,
            "precision": "bfloat16-autocast",
            "determinism": {
                "torch_deterministic_algorithms": True,
                "cudnn_benchmark": False,
                "cudnn_deterministic": True,
                "cublas_workspace_config": os.environ.get("CUBLAS_WORKSPACE_CONFIG"),
            },
            "class_weights": [float(value) for value in weights.cpu()],
            "class_weight_contract": {
                "profile": CLASS_WEIGHT_PROFILE,
                "hypothesis_id": HYPOTHESIS_ID,
                "scheme": weight_scheme,
                "denominator_classes": 10,
                "maximum_weight": maximum_weight,
                "selection_metric_uses_these_weights": False,
                "effective_weighted_mass": [float(value) for value in weighted_class_mass.cpu()],
                "status": "preregistered_controlled_ablation_never_public_test_selected",
            },
            "seeds": list(TRAINING_SEEDS),
            "selection": "minimum_internal_validation_cross_entropy",
            "test_usage": "development diagnostic only; observed in prior iterations",
            "published_test_status": "development_only_contaminated_by_prior_iteration",
            "sealed_final_holdout_status": "excluded_from_optimization_selection_and_metrics",
            "preregistered_hypothesis": {
                "id": HYPOTHESIS_ID,
                "statement": (
                    "compare one frozen class-weight profile under identical parser, split, "
                    "seeds, architecture and calibration; never select from the public test"
                ),
                "primary_metric": "internal_validation_cross_entropy",
                "decision_scope": "candidate_only_never_promotion",
                "sealed_holdout_consulted": False,
            },
            "gpu_at_training_start": gpu_snapshot(),
        },
        {
            "event": "dataset_prepared",
            "run_id": RUN_ID,
            "train_rows_seen": train_data.rows_seen,
            "train_eligible": len(train_data.targets),
            "train_parse_failures": train_data.parse_failures,
            "train_ambiguous_sizing": train_data.ambiguous_sizing,
            "validation_rows": int(validation_mask.sum()),
            "calibration_rows": int(calibration_mask.sum()),
            "calibration_check_rows": int(calibration_check_mask.sum()),
            "sealed_final_holdout_rows": int(sealed_final_holdout_mask.sum()),
            "sealed_final_holdout_unique_groups": len(sealed_final_holdout_groups),
            "sealed_final_holdout_split_id_commitment_sha256": hashlib.sha256(
                "\n".join(sorted(sealed_final_holdout_split_ids)).encode("ascii")
            ).hexdigest(),
            "sealed_final_holdout_feature_group_commitment_sha256": hashlib.sha256(
                "\n".join(sorted(sealed_final_holdout_groups)).encode("ascii")
            ).hexdigest(),
            "split_identity_contract": (
                "pokerbench-semantic-split-v1; suit-canonical public state; no solver label"
            ),
            "sealed_final_holdout_labels_scored": False,
            "validation_unique_groups": int(len(validation_groups)),
            "calibration_unique_groups": int(len(calibration_groups)),
            "calibration_check_unique_groups": int(len(calibration_check_groups)),
            "training_unique_groups": int(len(training_groups)),
            "cross_split_group_overlap": 0,
            "published_train_test_group_overlap": train_test_group_overlap,
            "published_overlap_examples_excluded": train_test_overlap_examples_excluded,
            "published_overlap_groups_excluded": train_test_overlap_groups_excluded,
            "download_elapsed_seconds": download_elapsed_seconds,
            "preparation_elapsed_seconds": preparation_elapsed_seconds,
            "test_input_rows_seen": test_inputs.rows_seen,
            "test_input_eligible": len(test_inputs.targets),
            "test_input_parse_failures": test_inputs.parse_failures,
            "test_input_targets_redacted": True,
            "optimization_training_class_counts": np.bincount(
                train_data.targets[training_mask], minlength=10
            ).tolist(),
            "validation_class_counts": np.bincount(
                train_data.targets[validation_mask], minlength=10
            ).tolist(),
            "calibration_class_counts": np.bincount(
                train_data.targets[calibration_mask], minlength=10
            ).tolist(),
            "calibration_check_class_counts": np.bincount(
                train_data.targets[calibration_check_mask], minlength=10
            ).tolist(),
            "label_consistency": label_consistency,
            "training_rows_with_reconstructed_history": int(
                np.count_nonzero(train_data.context[training_mask, 6])
            ),
            "validation_rows_with_reconstructed_history": int(
                np.count_nonzero(train_data.context[validation_mask, 6])
            ),
            "test_rows_with_reconstructed_history": int(
                np.count_nonzero(test_inputs.context[:, 6])
            ),
            "training_reconstructed_history_events": int(
                train_data.context[training_mask, 6].sum()
            ),
            "validation_reconstructed_history_events": int(
                train_data.context[validation_mask, 6].sum()
            ),
            "test_reconstructed_history_events": int(test_inputs.context[:, 6].sum()),
            "history_parser_contract": {
                "money_scale_tenths_of_bb": 10,
                "columns": [
                    "raw_lines",
                    "expected_action_tokens",
                    "emitted_action_events",
                    "forced_events",
                    "ignored_action_tokens",
                    "unknown_actor_events",
                    "dealt_cards",
                    "reconstructed_pot_units",
                    "reported_pot_units",
                ],
                "train_totals": train_data.history_audit.sum(axis=0).tolist(),
                "test_totals": test_inputs.history_audit.sum(axis=0).tolist(),
                "train_exact_action_fidelity": bool(
                    np.array_equal(train_data.history_audit[:, 1], train_data.history_audit[:, 2])
                    and not train_data.history_audit[:, 4].any()
                ),
                "test_exact_action_fidelity": bool(
                    np.array_equal(test_inputs.history_audit[:, 1], test_inputs.history_audit[:, 2])
                    and not test_inputs.history_audit[:, 4].any()
                ),
                "unknown_actor_policy": "reserved_encoder_slot_never_fabricated",
            },
            "train_source_audit": train_data.source_audit,
            "test_source_audit": test_inputs.source_audit,
        },
    ]
    for event in trace_events:
        print(json.dumps(event, sort_keys=True), flush=True)
    seed_results: list[dict[str, object]] = []
    selection_losses: list[float] = []
    states: list[dict[str, torch.Tensor]] = []
    for seed in TRAINING_SEEDS:
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        model = Core().to(device)
        decay_parameters = [
            parameter
            for parameter in model.parameters()
            if parameter.requires_grad and parameter.ndim >= 2
        ]
        no_decay_parameters = [
            parameter
            for parameter in model.parameters()
            if parameter.requires_grad and parameter.ndim < 2
        ]
        if (
            not decay_parameters
            or not no_decay_parameters
            or len({id(parameter) for parameter in (*decay_parameters, *no_decay_parameters)})
            != len(list(model.parameters()))
        ):
            raise RuntimeError("AdamW parameter grouping is incomplete or duplicated")
        optimizer = torch.optim.AdamW(
            [
                {"params": decay_parameters, "weight_decay": WEIGHT_DECAY},
                {"params": no_decay_parameters, "weight_decay": 0.0},
            ],
            lr=LEARNING_RATE,
        )
        best_state = None
        best_metrics: dict[str, float] | None = None
        best_epoch: int | None = None
        material_reference_loss = math.inf
        epochs_without_material_improvement = 0
        generator = torch.Generator(device=device).manual_seed(seed)
        for epoch in range(MAX_EPOCHS):
            epoch_started = time.perf_counter()
            model.train()
            order = torch.randperm(len(y_train), generator=generator, device=device)
            epoch_weighted_loss_numerator = 0.0
            epoch_weight_denominator = 0.0
            epoch_unweighted_loss_sum = 0.0
            epoch_examples = 0
            gradient_norm_sum = 0.0
            gradient_norm_max = 0.0
            gradient_steps = 0
            clipped_gradient_steps = 0
            for start_index in range(0, len(order), BATCH_SIZE):
                indexes = order[start_index : start_index + BATCH_SIZE]
                xb = x_train[indexes]
                yb = y_train[indexes]
                optimizer.zero_grad(set_to_none=True)
                with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                    logits = masked_logits(model, xb)
                    loss = criterion(logits, yb)
                if not torch.isfinite(loss):
                    raise RuntimeError("training loss became non-finite")
                loss.backward()
                gradient_norm = float(
                    nn.utils.clip_grad_norm_(model.parameters(), max_norm=GRADIENT_CLIP_NORM).item()
                )
                if not math.isfinite(gradient_norm):
                    raise RuntimeError("gradient norm became non-finite")
                if gradient_norm > GRADIENT_CLIP_NORM:
                    clipped_gradient_steps += 1
                optimizer.step()
                with torch.no_grad():
                    stable_logits = logits.detach().float()
                    epoch_weighted_loss_numerator += float(
                        nn.functional.cross_entropy(
                            stable_logits,
                            yb,
                            weight=weights,
                            reduction="sum",
                        ).item()
                    )
                    epoch_weight_denominator += float(weights[yb].sum().item())
                    epoch_unweighted_loss_sum += float(
                        nn.functional.cross_entropy(
                            stable_logits,
                            yb,
                            reduction="sum",
                        ).item()
                    )
                epoch_examples += len(yb)
                gradient_norm_sum += gradient_norm
                gradient_norm_max = max(gradient_norm_max, gradient_norm)
                gradient_steps += 1
            validation_metrics = metrics(model, x_val, y_val)
            observed: dict[str, object] = dict(validation_metrics)
            observed["epoch"] = epoch + 1
            observed["train_weighted_loss"] = (
                epoch_weighted_loss_numerator / epoch_weight_denominator
            )
            observed["train_unweighted_loss"] = epoch_unweighted_loss_sum / epoch_examples
            observed["gradient_norm_preclip_mean"] = gradient_norm_sum / gradient_steps
            observed["gradient_norm_preclip_max"] = gradient_norm_max
            observed["gradient_clip_threshold"] = GRADIENT_CLIP_NORM
            observed["gradient_clipped_steps"] = clipped_gradient_steps
            observed["gradient_total_steps"] = gradient_steps
            epoch_elapsed_seconds = time.perf_counter() - epoch_started
            observed["elapsed_seconds"] = epoch_elapsed_seconds
            observed["examples_per_second"] = epoch_examples / epoch_elapsed_seconds
            observed["gpu_after_epoch"] = gpu_snapshot()
            parameter_summary: dict[str, dict[str, float]] = {}
            with torch.no_grad():
                for name, parameter in model.named_parameters():
                    values = parameter.detach().float()
                    parameter_summary[name] = {
                        "min": float(values.min().item()),
                        "max": float(values.max().item()),
                        "mean": float(values.mean().item()),
                        "std": float(values.std().item()),
                        "l2_norm": float(values.norm().item()),
                    }
            epoch_event: dict[str, object] = {
                "event": "epoch_completed",
                "seed": seed,
                "parameter_summary": parameter_summary,
                **observed,
            }
            trace_events.append(epoch_event)
            print(json.dumps(epoch_event, sort_keys=True), flush=True)
            if best_metrics is None or validation_metrics["loss"] < best_metrics["loss"]:
                best_metrics = validation_metrics
                best_epoch = epoch + 1
                best_state = {
                    key: value.detach().cpu().clone() for key, value in model.state_dict().items()
                }
            if validation_metrics["loss"] < material_reference_loss - EARLY_STOPPING_MIN_DELTA:
                material_reference_loss = validation_metrics["loss"]
                epochs_without_material_improvement = 0
            else:
                epochs_without_material_improvement += 1
            if (
                epoch + 1 >= MIN_EPOCHS
                and epochs_without_material_improvement >= EARLY_STOPPING_PATIENCE
            ):
                stopping_event = {
                    "event": "early_stopping",
                    "seed": seed,
                    "completed_epochs": epoch + 1,
                    "best_epoch": best_epoch,
                    "material_reference_validation_nll": material_reference_loss,
                    "patience": EARLY_STOPPING_PATIENCE,
                    "min_delta": EARLY_STOPPING_MIN_DELTA,
                }
                trace_events.append(stopping_event)
                print(json.dumps(stopping_event, sort_keys=True), flush=True)
                break
        if best_state is None or best_metrics is None or best_epoch is None:
            raise RuntimeError("seed training produced no checkpoint")
        seed_results.append({"seed": seed, "best_epoch": best_epoch, "validation": best_metrics})
        selection_losses.append(best_metrics["loss"])
        states.append(best_state)

    selected_index = min(range(len(seed_results)), key=selection_losses.__getitem__)
    selected_seed = TRAINING_SEEDS[selected_index]
    selected = Core().to(device)
    selected.load_state_dict(states[selected_index])
    selected.eval()
    calibration_logits_parts = []
    calibration_check_logits_parts = []
    with torch.inference_mode():
        for start_index in range(0, len(y_calibration), EVALUATION_BATCH_SIZE):
            calibration_logits_parts.append(
                masked_logits(
                    selected,
                    x_calibration[start_index : start_index + EVALUATION_BATCH_SIZE],
                )
                .float()
                .detach()
            )
        for start_index in range(0, len(y_calibration_check), EVALUATION_BATCH_SIZE):
            calibration_check_logits_parts.append(
                masked_logits(
                    selected,
                    x_calibration_check[start_index : start_index + EVALUATION_BATCH_SIZE],
                )
                .float()
                .detach()
            )
    calibration_logits = torch.cat(calibration_logits_parts)
    calibration_check_logits = torch.cat(calibration_check_logits_parts)
    calibration_nll_before = float(
        nn.functional.cross_entropy(calibration_logits, y_calibration).item()
    )
    calibration_check_nll_before = float(
        nn.functional.cross_entropy(calibration_check_logits, y_calibration_check).item()
    )
    log_temperature = torch.zeros((), device=device, requires_grad=True)
    temperature_optimizer = torch.optim.LBFGS(
        [log_temperature],
        lr=0.1,
        max_iter=50,
        tolerance_grad=1e-9,
        tolerance_change=1e-12,
        line_search_fn="strong_wolfe",
    )
    lower_log_temperature = math.log(CALIBRATION_TEMPERATURE_MIN)
    upper_log_temperature = math.log(CALIBRATION_TEMPERATURE_MAX)

    def calibration_closure() -> torch.Tensor:
        temperature_optimizer.zero_grad(set_to_none=True)
        bounded_temperature = torch.exp(
            torch.clamp(log_temperature, lower_log_temperature, upper_log_temperature)
        )
        calibration_loss = nn.functional.cross_entropy(
            calibration_logits / bounded_temperature,
            y_calibration,
        )
        if not torch.isfinite(calibration_loss):
            raise RuntimeError("temperature calibration became non-finite")
        calibration_loss.backward()
        return calibration_loss

    temperature_optimizer.step(calibration_closure)
    optimized_log_temperature = float(log_temperature.detach().item())
    temperature = float(
        torch.exp(
            torch.clamp(
                log_temperature.detach(),
                lower_log_temperature,
                upper_log_temperature,
            )
        ).item()
    )
    calibration_nll_after = float(
        nn.functional.cross_entropy(calibration_logits / temperature, y_calibration).item()
    )
    calibration_check_nll_after = float(
        nn.functional.cross_entropy(
            calibration_check_logits / temperature,
            y_calibration_check,
        ).item()
    )
    if (
        not math.isfinite(temperature)
        or not math.isfinite(calibration_nll_after)
        or not math.isfinite(calibration_check_nll_before)
        or not math.isfinite(calibration_check_nll_after)
        or calibration_nll_after > calibration_nll_before + 1e-7
        or calibration_check_nll_after > calibration_check_nll_before + 1e-7
        or optimized_log_temperature <= lower_log_temperature + 1e-6
        or optimized_log_temperature >= upper_log_temperature - 1e-6
    ):
        raise RuntimeError("dedicated calibration partition did not produce a valid temperature")
    calibration_check_targets = y_calibration_check.detach().cpu().numpy()
    calibration_check_diagnostics_before = multiclass_probability_diagnostics(
        torch.softmax(calibration_check_logits, dim=1).cpu().numpy(),
        calibration_check_targets,
        bins=15,
    )
    calibration_check_diagnostics_after = multiclass_probability_diagnostics(
        torch.softmax(calibration_check_logits / temperature, dim=1).cpu().numpy(),
        calibration_check_targets,
        bins=15,
    )
    published_test_label_load_started = time.perf_counter()
    test_data = prepare_csv_files(
        [
            ("preflop_test", paths["preflop_test"]),
            ("postflop_test", paths["postflop_test"]),
        ]
    )
    published_test_label_load_elapsed_seconds = (
        time.perf_counter() - published_test_label_load_started
    )
    test_input_identity = {
        (str(source), int(row)): (index, str(group_id))
        for index, (source, row, group_id) in enumerate(
            zip(
                test_inputs.source_keys,
                test_inputs.row_numbers,
                test_inputs.group_ids,
                strict=True,
            )
        )
    }
    labelled_test_positions: list[int] = []
    labelled_test_identity_matches = True
    for source, row, group_id in zip(
        test_data.source_keys,
        test_data.row_numbers,
        test_data.group_ids,
        strict=True,
    ):
        input_identity = test_input_identity.get((str(source), int(row)))
        if input_identity is None or input_identity[1] != str(group_id):
            labelled_test_identity_matches = False
            break
        labelled_test_positions.append(input_identity[0])
    if (
        test_data.parse_failures
        or test_data.history_audit[:, 4].any()
        or not np.array_equal(test_data.history_audit[:, 1], test_data.history_audit[:, 2])
        or len(test_input_identity) != len(test_inputs.targets)
        or not labelled_test_identity_matches
        or labelled_test_positions != sorted(labelled_test_positions)
        or np.any(test_data.targets < 0)
    ):
        raise RuntimeError("post-selection published test diagnostic failed its input contract")
    label_consistency["published_development"] = group_label_audit(
        test_data.group_ids, test_data.targets
    )
    x_test = torch.from_numpy(test_data.features).to(device)
    y_test = torch.from_numpy(test_data.targets).to(device)
    test_metrics = metrics(selected, x_test, y_test, temperature=temperature)
    if not all(math.isfinite(float(value)) for value in test_metrics.values()):
        raise RuntimeError("test metrics are non-finite")

    ablation_slices = {
        "cards": slice(0, CARD_FEATURES),
        "global": slice(CARD_FEATURES, CARD_FEATURES + GLOBAL_FEATURES),
        "seats": slice(CARD_FEATURES + GLOBAL_FEATURES, STATIC_STATE_FEATURES),
        "history": slice(
            STATIC_STATE_FEATURES,
            STATIC_STATE_FEATURES + MAX_HISTORY * HISTORY_FEATURES,
        ),
    }
    feature_ablation = {}
    with torch.inference_mode():
        for name, feature_slice in ablation_slices.items():
            correct = top3_correct = total = 0
            for start_index in range(0, len(y_test), EVALUATION_BATCH_SIZE):
                xb = x_test[start_index : start_index + EVALUATION_BATCH_SIZE].clone()
                yb = y_test[start_index : start_index + EVALUATION_BATCH_SIZE]
                xb[:, feature_slice] = 0.0
                logits = masked_logits(selected, xb) / temperature
                correct += int((logits.argmax(1) == yb).sum().item())
                top3_correct += int(
                    (logits.topk(3, dim=1).indices == yb[:, None]).any(1).sum().item()
                )
                total += len(yb)
            feature_ablation[name] = {
                "accuracy": correct / total,
                "top3_accuracy": top3_correct / total,
                "accuracy_delta_from_unablated": correct / total - test_metrics["accuracy"],
                "interpretation": "diagnostic_only_not_causal",
            }

    confusion = np.zeros((10, 10), dtype=np.int64)
    calibration_count = np.zeros(15, dtype=np.int64)
    calibration_confidence = np.zeros(15, dtype=np.float64)
    calibration_correct = np.zeros(15, dtype=np.float64)
    development_probability_batches: list[np.ndarray] = []
    development_target_batches: list[np.ndarray] = []
    inference_lines: list[str] = []
    strata: dict[tuple[str, str], list[float]] = {}
    street_names = ("preflop", "flop", "turn", "river")
    selected.eval()
    with torch.inference_mode():
        for start_index in range(0, len(y_test), 4_096):
            xb = x_test[start_index : start_index + 4_096]
            yb = y_test[start_index : start_index + 4_096]
            logits = masked_logits(selected, xb) / temperature
            probabilities = torch.softmax(logits, dim=1)
            if not torch.isfinite(probabilities).all():
                raise RuntimeError("test probabilities became non-finite")
            development_probability_batches.append(probabilities.cpu().numpy())
            development_target_batches.append(yb.cpu().numpy())
            confidence, predicted = probabilities.max(dim=1)
            top_values, top_indices = probabilities.topk(3, dim=1)
            entropy = -(probabilities * probabilities.clamp_min(1e-12).log()).sum(dim=1)
            for local_index in range(len(yb)):
                absolute_index = start_index + local_index
                target = int(yb[local_index].item())
                prediction = int(predicted[local_index].item())
                observed_confidence = float(confidence[local_index].item())
                confusion[target, prediction] += 1
                bin_index = min(int(observed_confidence * 15), 14)
                calibration_count[bin_index] += 1
                calibration_confidence[bin_index] += observed_confidence
                calibration_correct[bin_index] += float(prediction == target)
                context = test_data.context[absolute_index]
                stratum_values = {
                    "source": str(test_data.source_keys[absolute_index]),
                    "street": street_names[int(context[0])],
                    "position": str(test_data.positions[absolute_index]),
                    "table_size": str(int(context[2])),
                    "target_action": str(target),
                    "legal_action_count": str(int(context[3])),
                    "history_present": str(bool(context[6])),
                }
                row_probabilities = probabilities[local_index]
                target_probability = float(row_probabilities[target].item())
                row_nll = -math.log(max(target_probability, 1e-12))
                row_brier = float(
                    sum(
                        (float(probability.item()) - float(index == target)) ** 2
                        for index, probability in enumerate(row_probabilities)
                    )
                )
                for axis, value in stratum_values.items():
                    accumulator = strata.setdefault((axis, value), [0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
                    accumulator[0] += 1.0
                    accumulator[1] += float(prediction == target)
                    accumulator[2] += observed_confidence
                    accumulator[3] += target_probability
                    accumulator[4] += row_nll
                    accumulator[5] += row_brier
                inference_lines.append(
                    json.dumps(
                        {
                            "source": str(test_data.source_keys[absolute_index]),
                            "row": int(test_data.row_numbers[absolute_index]),
                            "target": target,
                            "executed_modal": prediction,
                            "top3": [int(value) for value in top_indices[local_index].cpu()],
                            "top3_probability": [
                                round(float(value), 9) for value in top_values[local_index].cpu()
                            ],
                            "probabilities": [
                                round(float(value), 9) for value in probabilities[local_index].cpu()
                            ],
                            "target_probability": round(
                                float(probabilities[local_index, target].item()),
                                9,
                            ),
                            "entropy": round(float(entropy[local_index].item()), 9),
                            "street": stratum_values["street"],
                            "position": stratum_values["position"],
                            "table_size": int(context[2]),
                            "pot": int(context[4]),
                            "to_call": int(context[5]),
                            "history_expected_actions": int(
                                test_data.history_audit[absolute_index, 1]
                            ),
                            "history_emitted_actions": int(
                                test_data.history_audit[absolute_index, 2]
                            ),
                            "history_unknown_actor_events": int(
                                test_data.history_audit[absolute_index, 5]
                            ),
                            "history_reconstructed_pot": int(
                                test_data.history_audit[absolute_index, 7]
                            ),
                            "history_reported_pot": int(test_data.history_audit[absolute_index, 8]),
                            "history_pot_discrepancy": int(
                                test_data.history_audit[absolute_index, 7]
                                - test_data.history_audit[absolute_index, 8]
                            ),
                            "history_events": int(context[6]),
                            "legal_mask": [
                                int(value) for value in xb[local_index, -10:].cpu().tolist()
                            ],
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
    development_probabilities = np.concatenate(development_probability_batches)
    development_targets = np.concatenate(development_target_batches)
    development_probability_diagnostics: dict[str, object] = {
        "status": "development_only_contaminated_not_promotion_evidence",
        "calibration_bins": 15,
        **multiclass_probability_diagnostics(
            development_probabilities,
            development_targets,
            bins=15,
        ),
    }
    calibration = []
    expected_calibration_error = 0.0
    for index, count in enumerate(calibration_count):
        if count == 0:
            calibration.append({"bin": index, "count": 0})
            continue
        mean_confidence = calibration_confidence[index] / count
        mean_accuracy = calibration_correct[index] / count
        expected_calibration_error += (
            float(count) / len(y_test) * abs(mean_confidence - mean_accuracy)
        )
        calibration.append(
            {
                "bin": index,
                "count": int(count),
                "mean_confidence": mean_confidence,
                "accuracy": mean_accuracy,
            }
        )
    score_strata = [
        {
            "axis": axis,
            "value": value,
            "count": int(values[0]),
            "accuracy": values[1] / values[0],
            "mean_confidence": values[2] / values[0],
            "mean_target_probability": values[3] / values[0],
            "negative_log_likelihood": values[4] / values[0],
            "multiclass_brier_score": values[5] / values[0],
        }
        for (axis, value), values in sorted(strata.items())
    ]
    inference_trace = gzip.compress(
        ("\n".join(inference_lines) + "\n").encode("utf-8"),
        compresslevel=9,
        mtime=0,
    )
    selection_event: dict[str, object] = {
        "event": "candidate_selected",
        "selected_seed": selected_seed,
        "selection_basis": "minimum_internal_validation_cross_entropy",
        "published_development_test": test_metrics,
        "expected_calibration_error_15_bins": expected_calibration_error,
        "probability_calibration_applied": True,
        "temperature": temperature,
        "calibration_nll_before": calibration_nll_before,
        "calibration_nll_after": calibration_nll_after,
        "calibration_check_nll_before": calibration_check_nll_before,
        "calibration_check_nll_after": calibration_check_nll_after,
        "calibration_check_diagnostics_before": calibration_check_diagnostics_before,
        "calibration_check_diagnostics_after": calibration_check_diagnostics_after,
        "published_test_labels_loaded_only_after_selection": True,
        "published_test_label_load_elapsed_seconds": (published_test_label_load_elapsed_seconds),
        "development_probability_diagnostics": development_probability_diagnostics,
    }
    trace_events.append(selection_event)
    print(json.dumps(selection_event, sort_keys=True), flush=True)

    class ExportModel(nn.Module):
        def __init__(self, core: nn.Module, calibrated_temperature: float) -> None:
            super().__init__()
            self.core = core
            self.register_buffer(
                "temperature",
                torch.tensor(calibrated_temperature, dtype=torch.float32),
            )

        def forward(
            self,
            cards: torch.Tensor,
            global_features: torch.Tensor,
            seats: torch.Tensor,
            history: torch.Tensor,
            history_mask: torch.Tensor,
            legal_mask: torch.Tensor,
        ) -> torch.Tensor:
            batch = cards.shape[0]
            ordered_history = history * history_mask.reshape(batch, MAX_HISTORY, 1)
            features = torch.cat(
                (
                    cards,
                    global_features,
                    seats.reshape(batch, -1),
                    ordered_history.reshape(batch, -1),
                    legal_mask,
                ),
                dim=1,
            )
            return self.core(features) / self.temperature

    selected.eval()
    export = ExportModel(selected, temperature).cpu().eval()
    example_inputs = (
        torch.zeros(1, CARD_FEATURES),
        torch.zeros(1, GLOBAL_FEATURES),
        torch.zeros(1, MAX_SEATS, SEAT_FEATURES),
        torch.zeros(1, MAX_HISTORY, HISTORY_FEATURES),
        torch.zeros(1, MAX_HISTORY),
        torch.ones(1, 10),
    )
    onnx_buffer = io.BytesIO()
    torch.onnx.export(
        export,
        example_inputs,
        onnx_buffer,
        input_names=["cards", "global", "seats", "history", "history_mask", "legal_mask"],
        output_names=["logits"],
        dynamic_axes={
            "cards": {0: "batch"},
            "global": {0: "batch"},
            "seats": {0: "batch"},
            "history": {0: "batch"},
            "history_mask": {0: "batch"},
            "legal_mask": {0: "batch"},
            "logits": {0: "batch"},
        },
        opset_version=17,
        dynamo=False,
    )
    parity_rng = np.random.default_rng(20260808)
    parity_batch = 17
    parity_inputs = {
        "cards": parity_rng.integers(0, 2, (parity_batch, CARD_FEATURES)).astype(np.float32),
        "global": parity_rng.normal(size=(parity_batch, GLOBAL_FEATURES)).astype(np.float32),
        "seats": parity_rng.normal(size=(parity_batch, MAX_SEATS, SEAT_FEATURES)).astype(
            np.float32
        ),
        "history": parity_rng.normal(size=(parity_batch, MAX_HISTORY, HISTORY_FEATURES)).astype(
            np.float32
        ),
        "history_mask": np.zeros((parity_batch, MAX_HISTORY), dtype=np.float32),
        "legal_mask": np.ones((parity_batch, 10), dtype=np.float32),
    }
    for row_index in range(parity_batch):
        parity_inputs["history_mask"][row_index, : (row_index * 7) % (MAX_HISTORY + 1)] = 1.0
        parity_inputs["legal_mask"][row_index, (row_index + 3) % 10] = 0.0
    with torch.inference_mode():
        source_logits = export(
            *(
                torch.from_numpy(parity_inputs[name])
                for name in (
                    "cards",
                    "global",
                    "seats",
                    "history",
                    "history_mask",
                    "legal_mask",
                )
            )
        ).numpy()
    session = ort.InferenceSession(onnx_buffer.getvalue(), providers=["CPUExecutionProvider"])
    onnx_logits = session.run(["logits"], parity_inputs)[0]
    onnx_random_max_abs_error = float(np.max(np.abs(source_logits - onnx_logits)))
    real_flat = test_data.features[:parity_batch]
    real_history = real_flat[
        :,
        STATIC_STATE_FEATURES : STATIC_STATE_FEATURES + MAX_HISTORY * HISTORY_FEATURES,
    ].reshape(parity_batch, MAX_HISTORY, HISTORY_FEATURES)
    real_parity_inputs = {
        "cards": real_flat[:, :CARD_FEATURES],
        "global": real_flat[:, CARD_FEATURES : CARD_FEATURES + GLOBAL_FEATURES],
        "seats": real_flat[:, CARD_FEATURES + GLOBAL_FEATURES : STATIC_STATE_FEATURES].reshape(
            parity_batch, MAX_SEATS, SEAT_FEATURES
        ),
        "history": real_history,
        "history_mask": (np.abs(real_history).sum(axis=2) > 0.0).astype(np.float32),
        "legal_mask": real_flat[:, -10:],
    }
    with torch.inference_mode():
        real_source_logits = export(
            *(
                torch.from_numpy(real_parity_inputs[name])
                for name in (
                    "cards",
                    "global",
                    "seats",
                    "history",
                    "history_mask",
                    "legal_mask",
                )
            )
        ).numpy()
    real_onnx_logits = session.run(["logits"], real_parity_inputs)[0]
    onnx_real_max_abs_error = float(np.max(np.abs(real_source_logits - real_onnx_logits)))
    onnx_max_abs_error = max(onnx_random_max_abs_error, onnx_real_max_abs_error)
    if not math.isfinite(onnx_max_abs_error) or onnx_max_abs_error > ONNX_PARITY_MAX_ABS_ERROR:
        raise RuntimeError(f"ONNX export parity failed: {onnx_max_abs_error}")
    parity_event = {
        "event": "onnx_export_parity",
        "examples": parity_batch,
        "seed": 20260808,
        "max_abs_error": onnx_max_abs_error,
        "random_contract_max_abs_error": onnx_random_max_abs_error,
        "real_pokerbench_max_abs_error": onnx_real_max_abs_error,
        "threshold": ONNX_PARITY_MAX_ABS_ERROR,
        "includes_nonuniform_ordered_history": True,
        "includes_real_development_examples": True,
    }
    trace_events.append(parity_event)
    print(json.dumps(parity_event, sort_keys=True), flush=True)
    checkpoint_buffer = io.BytesIO()
    torch.save(
        {
            "state_dict": states[selected_index],
            "selected_seed": selected_seed,
            "seed_results": seed_results,
        },
        checkpoint_buffer,
    )
    training_trace = "".join(
        json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n" for event in trace_events
    )
    training_trace_bytes = training_trace.encode("utf-8")
    metadata = {
        "run_id": RUN_ID,
        "git_commit": GIT_COMMIT,
        "source_binding": SOURCE_BINDING,
        "source_components_sha256": {
            "package": PACKAGE_SOURCE_SHA256,
            "trainer": TRAINER_SHA256,
            "training_module": TRAINING_MODULE_SHA256,
            "dependency_lock": DEPENDENCY_LOCK_SHA256,
        },
        "release_status": "candidate_only_not_promoted",
        "purpose": PURPOSE,
        "class_weight_profile": CLASS_WEIGHT_PROFILE,
        "hypothesis_id": HYPOTHESIS_ID,
        "gpu": gpu_name,
        "vram_bytes": total_vram,
        "torch_version": torch.__version__,
        "numpy_version": np.__version__,
        "onnxruntime_version": ort.__version__,
        "cuda_version": torch.version.cuda,
        "cudnn_version": torch.backends.cudnn.version(),
        "compute_capability": list(torch.cuda.get_device_capability(0)),
        "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
        "environment_freeze": sorted(
            line
            for line in subprocess.check_output(
                [sys.executable, "-m", "pip", "freeze", "--all"],
                text=True,
                timeout=30,
            ).splitlines()
            if line.strip()
        ),
        "cuda_max_memory_allocated_bytes": torch.cuda.max_memory_allocated(),
        "cuda_max_memory_reserved_bytes": torch.cuda.max_memory_reserved(),
        "gpu_at_completion": gpu_snapshot(),
        "seeds": list(TRAINING_SEEDS),
        "selected_seed": selected_seed,
        "seed_results": seed_results,
        "published_development_test": test_metrics,
        "published_test_status": "development_only_contaminated_by_prior_iteration",
        "sealed_final_holdout_status": "excluded_from_optimization_selection_and_metrics",
        "test_confusion_matrix": confusion.tolist(),
        "development_reliability_15_bins": calibration,
        "development_expected_calibration_error_15_bins": expected_calibration_error,
        "development_probability_diagnostics": development_probability_diagnostics,
        "probability_calibration": {
            "applied": True,
            "method": "scalar_temperature_on_group_disjoint_calibration_partition",
            "temperature": temperature,
            "calibration_rows": int(calibration_mask.sum()),
            "calibration_unique_groups": int(len(calibration_groups)),
            "nll_before": calibration_nll_before,
            "nll_after": calibration_nll_after,
            "independent_check_rows": int(calibration_check_mask.sum()),
            "independent_check_unique_groups": int(len(calibration_check_groups)),
            "independent_check_nll_before": calibration_check_nll_before,
            "independent_check_nll_after": calibration_check_nll_after,
            "independent_check_diagnostics_before": calibration_check_diagnostics_before,
            "independent_check_diagnostics_after": calibration_check_diagnostics_after,
            "weights_frozen_before_calibration": True,
        },
        "test_score_strata": score_strata,
        "test_feature_group_ablation": feature_ablation,
        "onnx_max_abs_error": onnx_max_abs_error,
        "onnx_parity_examples": parity_batch,
        "unobserved_train_action_indices": [
            index
            for index, count in enumerate(
                np.bincount(train_data.targets[training_mask], minlength=10)
            )
            if count == 0
        ],
        "published_train_test_group_overlap": train_test_group_overlap,
        "published_overlap_examples_excluded": train_test_overlap_examples_excluded,
        "published_overlap_groups_excluded": train_test_overlap_groups_excluded,
        "download_elapsed_seconds": download_elapsed_seconds,
        "preparation_elapsed_seconds": preparation_elapsed_seconds,
        "train_rows_seen": train_data.rows_seen,
        "train_eligible": len(train_data.targets),
        "train_parse_failures": train_data.parse_failures,
        "train_ambiguous_sizing": train_data.ambiguous_sizing,
        "test_rows_seen": test_data.rows_seen,
        "test_eligible": len(test_data.targets),
        "test_parse_failures": test_data.parse_failures,
        "test_ambiguous_sizing": test_data.ambiguous_sizing,
        "training_rows_with_reconstructed_history": int(
            np.count_nonzero(train_data.context[training_mask, 6])
        ),
        "validation_rows_with_reconstructed_history": int(
            np.count_nonzero(train_data.context[validation_mask, 6])
        ),
        "test_rows_with_reconstructed_history": int(np.count_nonzero(test_data.context[:, 6])),
        "training_reconstructed_history_events": int(train_data.context[training_mask, 6].sum()),
        "validation_reconstructed_history_events": int(
            train_data.context[validation_mask, 6].sum()
        ),
        "test_reconstructed_history_events": int(test_data.context[:, 6].sum()),
        "elapsed_seconds": time.perf_counter() - started,
        "dataset_sha256": {key: value[1] for key, value in POKERBENCH_FILES.items()},
        "artifact_sha256": {
            "onnx": hashlib.sha256(onnx_buffer.getvalue()).hexdigest(),
            "checkpoint": hashlib.sha256(checkpoint_buffer.getvalue()).hexdigest(),
            "training_trace": hashlib.sha256(training_trace_bytes).hexdigest(),
            "inference_trace_gzip": hashlib.sha256(inference_trace).hexdigest(),
        },
    }
    print(json.dumps(metadata, sort_keys=True))
    temporary_directory.cleanup()
    return {
        "onnx": onnx_buffer.getvalue(),
        "checkpoint": checkpoint_buffer.getvalue(),
        "training_trace": training_trace_bytes,
        "inference_trace_gzip": inference_trace,
        "metadata": metadata,
    }


@app.local_entrypoint()
def main(output_dir: str) -> None:
    if (
        RUN_ID == "unconfigured"
        or re.fullmatch(r"poker-expert-v2-[0-9]{8}t[0-9]{6}z-[0-9a-f]{8}", RUN_ID) is None
        or re.fullmatch(r"[0-9a-f]{40}", GIT_COMMIT) is None
        or re.fullmatch(r"[0-9a-f]{64}", SOURCE_BINDING) is None
        or SOURCE_BINDING != CALCULATED_SOURCE_BINDING
        or WEIGHT_HYPOTHESES.get(CLASS_WEIGHT_PROFILE) != HYPOTHESIS_ID
    ):
        raise RuntimeError("set the run identity and source binding before launch")
    destination = _candidate_destination(
        output_dir,
        backend_root=BACKEND_ROOT,
        run_id=RUN_ID,
    )
    if destination.exists():
        raise FileExistsError(f"candidate output already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    import tempfile

    with tempfile.TemporaryDirectory(
        dir=destination.parent,
        prefix=f".{destination.name}.partial-",
    ) as temporary:
        staging = Path(temporary)
        result = train.remote()
        _verify_remote_result(result, run_id=RUN_ID, source_binding=SOURCE_BINDING)
        (staging / "poker_expert_v2.onnx").write_bytes(result["onnx"])
        (staging / "poker_expert_v2.source.pt").write_bytes(result["checkpoint"])
        (staging / "training_metrics.json").write_text(
            json.dumps(result["metadata"], sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        (staging / "training_trace.jsonl").write_bytes(result["training_trace"])
        (staging / "development_inference_trace.jsonl.gz").write_bytes(
            result["inference_trace_gzip"]
        )
        staged_hashes = {
            "onnx": _sha256_file(staging / "poker_expert_v2.onnx"),
            "checkpoint": _sha256_file(staging / "poker_expert_v2.source.pt"),
            "training_trace": _sha256_file(staging / "training_trace.jsonl"),
            "inference_trace_gzip": _sha256_file(staging / "development_inference_trace.jsonl.gz"),
        }
        if staged_hashes != result["metadata"]["artifact_sha256"]:
            raise RuntimeError("staged candidate differs from the verified remote payload")
        staging.replace(destination)
    print(destination)
