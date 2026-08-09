from __future__ import annotations

import ast
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "train_expert_v2_modal.py"


def _resolve_function():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_resolve_backend_root"
    )
    module = ast.Module(body=[function], type_ignores=[])
    namespace = {"Path": Path}
    exec(compile(module, str(SCRIPT), "exec"), namespace)  # noqa: S102 - isolated local AST
    return namespace["_resolve_backend_root"]


def _materialize_backend(root: Path, script_relative: Path) -> Path:
    script = root / script_relative
    script.parent.mkdir(parents=True)
    script.write_text("# test layout\n", encoding="utf-8")
    training_module = root / "poker_arena" / "ml" / "expert_training_v2.py"
    training_module.parent.mkdir(parents=True)
    training_module.write_text("# test module\n", encoding="utf-8")
    (root / "uv.lock").write_text("# test lock\n", encoding="utf-8")
    return script


def test_backend_root_resolves_checkout_and_modal_layouts(tmp_path: Path) -> None:
    resolve = _resolve_function()
    checkout = tmp_path / "checkout" / "backend"
    checkout_script = _materialize_backend(checkout, Path("scripts/train_expert_v2_modal.py"))
    modal_root = tmp_path / "modal-root"
    modal_script = _materialize_backend(modal_root, Path("train_expert_v2_modal.py"))

    assert resolve(checkout_script) == checkout
    assert resolve(modal_script) == modal_root


def test_backend_root_fails_closed_when_remote_files_are_absent(tmp_path: Path) -> None:
    resolve = _resolve_function()
    script = tmp_path / "root" / "train_expert_v2_modal.py"
    script.parent.mkdir()
    script.write_text("# missing image files\n", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="expert_training_v2.py or uv.lock"):
        resolve(script)


def test_modal_image_copies_the_lock_used_by_remote_binding() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert '.add_local_file(BACKEND_ROOT / "uv.lock", "/root/uv.lock", copy=True)' in source
    assert "BACKEND_ROOT = _resolve_backend_root(Path(__file__))" in source
    assert "Path('/root/uv.lock').is_file()" in source
    assert "Path('/root/poker_arena/ml/expert_training_v2.py').is_file()" in source
    assert '"numpy==2.4.6"' in source
    assert '"onnx==1.22.0"' in source
    assert '"onnxruntime==1.27.0"' in source
    assert "environment_freeze" in source


def test_local_publication_is_identity_bound_and_digest_verified() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "destination = _candidate_destination(" in source
    assert "_verify_remote_result(result, run_id=RUN_ID, source_binding=SOURCE_BINDING)" in source
    assert 'if staged_hashes != result["metadata"]["artifact_sha256"]:' in source
    assert "staging.replace(destination)" in source


def test_calibration_is_group_disjoint_frozen_and_exported() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "calibration_mask = split.calibration_mask" in source
    assert "calibration_check_mask = split.calibration_check_mask" in source
    assert "y_calibration = torch.from_numpy(train_data.targets[calibration_mask])" in source
    assert "redact_split_member=sealed_final_holdout_member" in source
    assert "sealed final holdout labels were consulted before partitioning" in source
    assert "selected.load_state_dict(states[selected_index])" in source
    assert "temperature_optimizer = torch.optim.LBFGS(" in source
    assert "calibration_check_nll_after > calibration_check_nll_before" in source
    assert "ExportModel(selected, temperature)" in source
    assert "return self.core(features) / self.temperature" in source


def test_history_model_uses_shared_causal_encoder_not_flat_position_weights() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "nn.GRU(" in source
    assert '"history_encoder": "causal_gru_shared_weights"' in source
    assert '"history_shape": [MAX_HISTORY, HISTORY_FEATURES]' in source
    assert "assert COMPRESSED_FEATURES == 740" in source


def test_adamw_does_not_decay_bias_or_normalization_parameters() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "parameter.ndim >= 2" in source
    assert "parameter.ndim < 2" in source
    assert '{"params": no_decay_parameters, "weight_decay": 0.0}' in source
    assert "AdamW parameter grouping is incomplete or duplicated" in source


def test_epoch_budget_uses_traced_validation_early_stopping_not_a_six_epoch_cutoff() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "MAX_EPOCHS = 24" in source
    assert "MIN_EPOCHS = 8" in source
    assert "EARLY_STOPPING_PATIENCE = 4" in source
    assert "EARLY_STOPPING_MIN_DELTA = 1e-4" in source
    assert '"event": "early_stopping"' in source
    assert "for epoch in range(MAX_EPOCHS)" in source


def test_modal_app_stays_within_the_platform_eight_tag_limit() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    tags_body = source.split("tags={", 1)[1].split("},", 1)[0]

    assert tags_body.count('":') == 8
    assert '"owner": "codex"' in tags_body
    assert '"run_id": RUN_ID' in tags_body


def test_onnx_parity_covers_real_and_adversarial_feature_tensors() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "onnx_random_max_abs_error" in source
    assert "onnx_real_max_abs_error" in source
    assert '"includes_real_development_examples": True' in source
    assert "max(onnx_random_max_abs_error, onnx_real_max_abs_error)" in source


def test_published_test_labels_are_not_loaded_before_model_and_calibration_selection() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    redacted_load = source.index("test_inputs = prepare_csv_files(")
    model_selection = source.index("selected.load_state_dict(states[selected_index])")
    labelled_load = source.index("test_data = prepare_csv_files(")
    assert redacted_load < model_selection < labelled_load
    assert "redact_split_member=lambda _split_id: True" in source
    assert "published test labels were consulted before candidate selection" in source


def test_weight_ablation_is_preregistered_and_public_test_cannot_select_it() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert '"uniform": "H-WEIGHT-UNIFORM-CONTROL-V1"' in source
    assert '"inverse_sqrt_cap5": "H-WEIGHT-INVSQRT-CAP5-V1"' in source
    assert '"primary_metric": "internal_validation_cross_entropy"' in source
    assert '"selection": "minimum_internal_validation_cross_entropy"' in source
    assert '"status": "preregistered_controlled_ablation_never_public_test_selected"' in source
