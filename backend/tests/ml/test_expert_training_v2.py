from __future__ import annotations

import csv
import hashlib
from dataclasses import replace

import numpy as np
import pytest

from poker_arena.bots.observation import Observation, PublicPlayer
from poker_arena.engine.actions import ActionType
from poker_arena.engine.cards import Card, Rank, Suit
from poker_arena.ml import expert_training_v2
from poker_arena.ml.encoder_v2 import (
    CARD_FEATURES,
    HISTORY_FEATURES,
    MAX_HISTORY,
    EncodedObservationV2,
)
from poker_arena.ml.expert_training_v2 import (
    COMPRESSED_FEATURES,
    STATIC_STATE_FEATURES,
    class_weights_for_profile,
    compressed_features,
    decontaminated_split,
    group_label_audit,
    internal_calibration_check_member,
    internal_calibration_member,
    internal_validation_member,
    multiclass_probability_diagnostics,
    prepare_csv_files,
    sealed_final_holdout_member,
    stable_split_id,
)


def _encoded(*, nonfinite: bool = False) -> EncodedObservationV2:
    history = [[0.0] * HISTORY_FEATURES for _ in range(MAX_HISTORY)]
    history[0][0] = float("nan") if nonfinite else 0.2
    history[1][0] = 0.4
    return EncodedObservationV2(
        cards=(0.0,) * CARD_FEATURES,
        global_features=(0.0,) * 24,
        seats=tuple((0.0,) * 12 for _ in range(9)),
        history=tuple(tuple(row) for row in history),
        history_mask=(1.0, 1.0, *([0.0] * (MAX_HISTORY - 2))),
        legal_mask=(1.0,) * 10,
    )


def test_compressed_features_preserve_ordered_history_bins() -> None:
    observed = compressed_features(_encoded())

    assert observed.shape == (COMPRESSED_FEATURES,)
    history_offset = STATIC_STATE_FEATURES
    assert observed[history_offset] == pytest.approx(0.2)
    assert observed[history_offset + HISTORY_FEATURES] == pytest.approx(0.4)
    assert np.isfinite(observed).all()


def test_compressed_features_are_sensitive_to_action_order_inside_a_bin() -> None:
    first = _encoded()
    history = [list(row) for row in first.history]
    history[0][0], history[1][0] = 0.2, 0.9
    forward = EncodedObservationV2(
        cards=first.cards,
        global_features=first.global_features,
        seats=first.seats,
        history=tuple(tuple(row) for row in history),
        history_mask=(1.0, 1.0, *([0.0] * (MAX_HISTORY - 2))),
        legal_mask=first.legal_mask,
    )
    reversed_history = [list(row) for row in history]
    reversed_history[0], reversed_history[1] = reversed_history[1], reversed_history[0]
    reverse = EncodedObservationV2(
        cards=forward.cards,
        global_features=forward.global_features,
        seats=forward.seats,
        history=tuple(tuple(row) for row in reversed_history),
        history_mask=forward.history_mask,
        legal_mask=forward.legal_mask,
    )

    assert not np.array_equal(compressed_features(forward), compressed_features(reverse))


def test_complete_history_has_no_abba_baab_pooling_collision() -> None:
    base = _encoded()
    abba_rows = [[0.0] * HISTORY_FEATURES for _ in range(MAX_HISTORY)]
    baab_rows = [[0.0] * HISTORY_FEATURES for _ in range(MAX_HISTORY)]
    for index, value in enumerate((0.2, 0.9, 0.9, 0.2)):
        abba_rows[index][0] = value
    for index, value in enumerate((0.9, 0.2, 0.2, 0.9)):
        baab_rows[index][0] = value
        mask = (1.0, 1.0, 1.0, 1.0, *([0.0] * (MAX_HISTORY - 4)))

    def with_history(rows: list[list[float]]) -> EncodedObservationV2:
        return EncodedObservationV2(
            cards=base.cards,
            global_features=base.global_features,
            seats=base.seats,
            history=tuple(tuple(row) for row in rows),
            history_mask=mask,
            legal_mask=base.legal_mask,
        )

    assert not np.array_equal(
        compressed_features(with_history(abba_rows)),
        compressed_features(with_history(baab_rows)),
    )


def test_compressed_features_reject_nonfinite_input() -> None:
    with pytest.raises(ValueError, match="compressed feature contract"):
        compressed_features(_encoded(nonfinite=True))


def test_compressed_features_reject_out_of_range_input() -> None:
    encoded = _encoded()
    history = [list(row) for row in encoded.history]
    history[0][0] = 1.0001
    invalid = EncodedObservationV2(
        cards=encoded.cards,
        global_features=encoded.global_features,
        seats=encoded.seats,
        history=tuple(tuple(row) for row in history),
        history_mask=encoded.history_mask,
        legal_mask=encoded.legal_mask,
    )
    with pytest.raises(ValueError, match="compressed feature contract"):
        compressed_features(invalid)


def test_compressed_features_reject_fractional_masks() -> None:
    encoded = _encoded()
    invalid = EncodedObservationV2(
        cards=encoded.cards,
        global_features=encoded.global_features,
        seats=encoded.seats,
        history=encoded.history,
        history_mask=(0.5, *encoded.history_mask[1:]),
        legal_mask=encoded.legal_mask,
    )
    with pytest.raises(ValueError, match="masks must be exactly binary"):
        compressed_features(invalid)


def test_compressed_features_reject_nonprefix_or_nonzero_padding() -> None:
    encoded = _encoded()
    nonprefix = EncodedObservationV2(
        cards=encoded.cards,
        global_features=encoded.global_features,
        seats=encoded.seats,
        history=encoded.history,
        history_mask=(1.0, 0.0, 1.0, *([0.0] * (MAX_HISTORY - 3))),
        legal_mask=encoded.legal_mask,
    )
    with pytest.raises(ValueError, match="contiguous one-prefix"):
        compressed_features(nonprefix)
    history = [list(row) for row in encoded.history]
    history[2][0] = 0.1
    nonzero_padding = EncodedObservationV2(
        cards=encoded.cards,
        global_features=encoded.global_features,
        seats=encoded.seats,
        history=tuple(tuple(row) for row in history),
        history_mask=encoded.history_mask,
        legal_mask=encoded.legal_mask,
    )
    with pytest.raises(ValueError, match="padded history rows"):
        compressed_features(nonzero_padding)


def test_class_weight_profiles_are_exact_finite_and_capped() -> None:
    counts = np.asarray([100, 25, 4, 0, 1, 10, 50, 2, 0, 8], dtype=np.int64)
    uniform = class_weights_for_profile(counts, "uniform")
    weighted = class_weights_for_profile(counts, "inverse_sqrt_cap5")

    np.testing.assert_array_equal(uniform, np.ones(10))
    expected = np.minimum(np.sqrt(counts.sum() / np.maximum(counts * 10, 1)), 5.0)
    np.testing.assert_allclose(weighted, expected, rtol=0.0, atol=0.0)
    assert np.isfinite(weighted).all()
    assert np.all((weighted > 0.0) & (weighted <= 5.0))


@pytest.mark.parametrize(
    ("counts", "profile"),
    [
        (np.ones(9, dtype=np.int64), "uniform"),
        (np.zeros(10, dtype=np.int64), "uniform"),
        (np.ones(10, dtype=np.float64), "uniform"),
        (np.ones(10, dtype=np.int64), "unregistered"),
    ],
)
def test_class_weight_profiles_fail_closed(counts: np.ndarray, profile: str) -> None:
    with pytest.raises(ValueError):
        class_weights_for_profile(counts, profile)


def test_probability_diagnostics_include_zero_support_class_anomalies() -> None:
    probabilities = np.zeros((4, 10), dtype=np.float64)
    targets = np.asarray([0, 1, 0, 1], dtype=np.int64)
    probabilities[np.arange(4), targets] = 0.6
    probabilities[:, 9] = 0.4

    observed = multiclass_probability_diagnostics(probabilities, targets, bins=2)

    assert observed["accuracy"] == pytest.approx(1.0)
    assert observed["multiclass_brier_score"] == pytest.approx(0.32)
    assert observed["unsupported_classes_mean_total_probability"] == pytest.approx(0.4)
    assert observed["unsupported_classes_max_total_probability"] == pytest.approx(0.4)
    assert observed["unsupported_classes_modal_predictions"] == 0
    per_class = observed["per_class"]
    assert isinstance(per_class, list)
    assert per_class[9]["support"] == 0
    assert per_class[9]["classwise_ece"] == pytest.approx(0.4)


def test_probability_diagnostics_reject_invalid_distributions_and_targets() -> None:
    probabilities = np.zeros((2, 10), dtype=np.float64)
    probabilities[:, 0] = 1.0
    with pytest.raises(ValueError, match="aligned integer"):
        multiclass_probability_diagnostics(probabilities, np.asarray([0.0, 0.0]), bins=2)
    probabilities[0, 1] = 0.1
    with pytest.raises(ValueError, match="normalized distributions"):
        multiclass_probability_diagnostics(
            probabilities,
            np.asarray([0, 0], dtype=np.int64),
            bins=2,
        )


def test_probability_diagnostics_accept_float32_softmax_rounding_then_renormalize() -> None:
    probabilities = np.zeros((2, 10), dtype=np.float32)
    probabilities[0, :2] = (0.5000001, 0.5000001)
    probabilities[1, :2] = (0.25, 0.75)
    observed = multiclass_probability_diagnostics(
        probabilities,
        np.asarray([0, 1], dtype=np.int64),
        bins=2,
    )

    assert observed["accuracy"] == pytest.approx(1.0)
    assert np.isfinite(float(observed["multiclass_brier_score"]))


@pytest.mark.parametrize(
    "targets",
    [
        np.asarray([0.9], dtype=np.float64),
        np.asarray([10], dtype=np.int64),
        np.asarray([-1], dtype=np.int64),
    ],
)
def test_group_label_audit_rejects_invalid_target_types_and_ranges(targets: np.ndarray) -> None:
    with pytest.raises(ValueError, match="valid integer class targets"):
        group_label_audit(np.asarray(["a" * 64]), targets)


def test_internal_validation_split_is_deterministic_and_non_degenerate() -> None:
    groups = [f"{row:064x}" for row in range(10_000)]
    first = [internal_validation_member(group) for group in groups]
    second = [internal_validation_member(group) for group in groups]

    assert first == second
    assert 850 <= sum(first) <= 1_150
    assert internal_validation_member(groups[4]) == internal_validation_member(groups[4])
    with pytest.raises(ValueError, match="group id"):
        internal_validation_member("not-a-digest")


def test_sealed_final_holdout_is_deterministic_and_distinct() -> None:
    groups = [f"{row:064x}" for row in range(10_000)]
    observed = [sealed_final_holdout_member(group) for group in groups]

    assert 400 <= sum(observed) <= 600
    assert observed == [sealed_final_holdout_member(group) for group in groups]
    with pytest.raises(ValueError, match="sealed holdout"):
        sealed_final_holdout_member("not-a-digest")


def test_calibration_partition_is_deterministic_and_validated() -> None:
    groups = [f"{index:064x}" for index in range(100)]
    observed = [internal_calibration_member(group) for group in groups]

    assert any(observed) and not all(observed)
    assert observed == [internal_calibration_member(group) for group in groups]
    with pytest.raises(ValueError, match="calibration group"):
        internal_calibration_member("not-a-digest")


def test_calibration_check_partition_is_deterministic_and_validated() -> None:
    groups = [f"{index:064x}" for index in range(100)]
    observed = [internal_calibration_check_member(group) for group in groups]

    assert any(observed) and not all(observed)
    assert observed == [internal_calibration_check_member(group) for group in groups]
    with pytest.raises(ValueError, match="calibration-check group"):
        internal_calibration_check_member("not-a-digest")


def test_published_test_groups_are_excluded_before_internal_split() -> None:
    groups = np.asarray([f"{row:064x}" for row in range(100)])
    duplicated_test_groups = np.asarray([groups[2], groups[2], groups[7]])

    split = decontaminated_split(groups, groups, duplicated_test_groups)

    assert split.overlap_example_count == 2
    assert split.overlap_group_count == 2
    assert not split.training_mask[2] and not split.validation_mask[2]
    assert not split.training_mask[7] and not split.validation_mask[7]
    assert not np.any(split.training_mask & split.validation_mask)
    assert not np.any(split.training_mask & split.calibration_mask)
    assert not np.any(split.training_mask & split.calibration_check_mask)
    assert not np.any(split.training_mask & split.sealed_final_holdout_mask)
    assert not np.any(split.validation_mask & split.calibration_mask)
    assert not np.any(split.validation_mask & split.calibration_check_mask)
    assert not np.any(split.validation_mask & split.sealed_final_holdout_mask)
    assert not np.any(split.calibration_mask & split.sealed_final_holdout_mask)
    assert not np.any(split.calibration_mask & split.calibration_check_mask)
    assert not np.any(split.calibration_check_mask & split.sealed_final_holdout_mask)
    assert not split.sealed_final_holdout_mask[2]
    assert not split.sealed_final_holdout_mask[7]
    assert not split.calibration_mask[2]
    assert not split.calibration_mask[7]
    assert not split.calibration_check_mask[2]
    assert not split.calibration_check_mask[7]


def test_stable_split_identity_is_semantic_and_suit_canonical() -> None:
    base = Observation(
        seat=0,
        hole=(Card(Rank.ACE, Suit.SPADES), Card(Rank.KING, Suit.HEARTS)),
        board=(),
        pot=45,
        to_call=20,
        current_bet=20,
        min_raise_to=40,
        legal_actions=frozenset({ActionType.FOLD, ActionType.CALL, ActionType.RAISE}),
        players=(
            PublicPlayer(0, "hero", 980, 0, 20, "active", True),
            PublicPlayer(1, "villain", 980, 20, 20, "active", False),
        ),
        num_active=2,
    )
    suit_isomorphic = replace(
        base,
        hole=(Card(Rank.ACE, Suit.CLUBS), Card(Rank.KING, Suit.DIAMONDS)),
    )

    assert stable_split_id(base) == stable_split_id(suit_isomorphic)
    assert stable_split_id(base) != stable_split_id(replace(base, pot=50))


def test_group_label_audit_exposes_irreducible_exact_feature_conflicts() -> None:
    groups = np.asarray(["a" * 64, "a" * 64, "b" * 64, "c" * 64, "c" * 64])
    targets = np.asarray([0, 1, 2, 3, 3], dtype=np.int64)

    assert group_label_audit(groups, targets) == {
        "examples": 5,
        "unique_groups": 3,
        "duplicate_examples": 2,
        "conflicting_groups": 1,
        "examples_in_conflicting_groups": 2,
        "exact_feature_top1_ceiling": 0.8,
    }


def test_group_label_audit_rejects_redacted_or_misaligned_targets() -> None:
    with pytest.raises(ValueError, match="valid integer class targets"):
        group_label_audit(np.asarray(["a" * 64]), np.asarray([-1]))
    with pytest.raises(ValueError, match="aligned"):
        group_label_audit(np.asarray(["a" * 64]), np.asarray([0, 1]))


def test_training_loader_redacts_partition_before_reading_invalid_label(
    tmp_path, monkeypatch
) -> None:
    path = tmp_path / "synthetic.csv"
    row = {
        "hero_holding": "AsKd",
        "pot_size": "1.5",
        "hero_pos": "SB",
        "num_players": "1",
        "available_moves": "['3.0bb', 'call', 'fold']",
        "prev_line": "",
        "correct_decision": "INVALID_LABEL_MUST_NOT_BE_CONSULTED",
    }
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setitem(expert_training_v2.POKERBENCH_FILES, "preflop_train", (path.name, digest))
    semantic_split_id = "a" * 64
    monkeypatch.setattr(
        expert_training_v2,
        "stable_split_id",
        lambda _observation: semantic_split_id,
    )

    prepared = prepare_csv_files(
        [("preflop_train", path)],
        redact_split_member=lambda split_id: split_id == semantic_split_id,
    )

    assert prepared.targets.tolist() == [-1]
    assert prepared.split_ids.tolist() == [semantic_split_id]
    assert prepared.group_ids.tolist() != prepared.split_ids.tolist()
    assert prepared.parse_failures == 0
    assert prepared.ambiguous_sizing == 0
