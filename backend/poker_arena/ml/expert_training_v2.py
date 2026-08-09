"""Deterministic PokerBench warm-start preparation for Expert v2."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np

from poker_arena.bots.observation import Observation
from poker_arena.ml.encoder_v2 import (
    CARD_FEATURES,
    GLOBAL_FEATURES,
    HISTORY_FEATURES,
    MAX_HISTORY,
    MAX_SEATS,
    SEAT_FEATURES,
    EncodedObservationV2,
)
from poker_arena.ml.pokerbench import featurize_v2_input, target_v2

POKERBENCH_FILES: Final = {
    "preflop_train": (
        "preflop_60k_train_set_game_scenario_information.csv",
        "5786fe9b2e34b593cd68e9c426cfce1a0ca845d0c45a27e8471ef3ad38657e69",
    ),
    "postflop_train": (
        "postflop_500k_train_set_game_scenario_information.csv",
        "a26f166b6cfbeb4cec5ab497016a1efaae058cd7a955ab0089603af2efb0c0b3",
    ),
    "preflop_test": (
        "preflop_1k_test_set_game_scenario_information.csv",
        "38710b92bbefbaa881c8b16e0d617152dc3606866ed9a88b3687b1194f2203e5",
    ),
    "postflop_test": (
        "postflop_10k_test_set_game_scenario_information.csv",
        "cfa73be8948c9927e6f3a7d73c26dd23160d04bb9cc9691ff6408c04cb4178a2",
    ),
}
STATIC_STATE_FEATURES: Final = CARD_FEATURES + GLOBAL_FEATURES + MAX_SEATS * SEAT_FEATURES
COMPRESSED_FEATURES: Final = STATIC_STATE_FEATURES + MAX_HISTORY * HISTORY_FEATURES + 10
CLASS_COUNT: Final = 10
MAX_INVERSE_SQRT_WEIGHT: Final = 5.0


@dataclass(frozen=True, slots=True)
class PreparedDataset:
    features: np.ndarray
    targets: np.ndarray
    source_keys: np.ndarray
    row_numbers: np.ndarray
    group_ids: np.ndarray
    split_ids: np.ndarray
    context: np.ndarray
    positions: np.ndarray
    history_audit: np.ndarray
    source_audit: tuple[tuple[str, int, int, int, int], ...]
    rows_seen: int
    parse_failures: int
    ambiguous_sizing: int


@dataclass(frozen=True, slots=True)
class DecontaminatedSplit:
    training_mask: np.ndarray
    validation_mask: np.ndarray
    calibration_mask: np.ndarray
    calibration_check_mask: np.ndarray
    sealed_final_holdout_mask: np.ndarray
    overlap_example_count: int
    overlap_group_count: int


def class_weights_for_profile(class_counts: np.ndarray, profile: str) -> np.ndarray:
    """Derive the exact preregistered loss weights from observed training counts."""

    counts = np.asarray(class_counts)
    if counts.shape != (CLASS_COUNT,):
        raise ValueError("class counts must have exactly ten entries")
    if not np.issubdtype(counts.dtype, np.integer) or np.any(counts < 0):
        raise ValueError("class counts must be non-negative integers")
    total = int(counts.sum())
    if total <= 0:
        raise ValueError("class counts must contain at least one example")
    if profile == "uniform":
        weights = np.ones(CLASS_COUNT, dtype=np.float64)
    elif profile == "inverse_sqrt_cap5":
        denominator = np.maximum(counts.astype(np.float64) * CLASS_COUNT, 1.0)
        weights = np.minimum(
            np.sqrt(total / denominator),
            MAX_INVERSE_SQRT_WEIGHT,
        )
    else:
        raise ValueError("class-weight profile is not preregistered")
    if not np.isfinite(weights).all() or np.any(weights <= 0.0):
        raise ValueError("class-weight profile produced invalid weights")
    return weights


def multiclass_probability_diagnostics(
    probabilities: np.ndarray,
    targets: np.ndarray,
    *,
    bins: int = 15,
) -> dict[str, object]:
    """Compute auditable probability metrics without hiding unsupported classes."""

    observed = np.asarray(probabilities, dtype=np.float64)
    labels = np.asarray(targets)
    if observed.ndim != 2 or observed.shape[1] != CLASS_COUNT or not len(observed):
        raise ValueError("probabilities must be a non-empty N x 10 matrix")
    if labels.shape != (len(observed),) or not np.issubdtype(labels.dtype, np.integer):
        raise ValueError("targets must be an aligned integer vector")
    if np.any(labels < 0) or np.any(labels >= CLASS_COUNT):
        raise ValueError("targets contain an invalid class index")
    if bins < 2 or bins > len(observed):
        raise ValueError("calibration bins must be between 2 and the example count")
    row_sums = observed.sum(axis=1)
    if (
        not np.isfinite(observed).all()
        or np.any(observed < 0.0)
        or not np.allclose(row_sums, 1.0, rtol=0.0, atol=1e-6)
    ):
        raise ValueError("probabilities are not finite normalized distributions")
    # Torch softmax is float32 in this pipeline. Normalize in float64 after a
    # bounded validation so downstream Brier/ECE arithmetic is exact and stable.
    observed = observed / row_sums[:, None]

    predictions = observed.argmax(axis=1)
    confidences = observed.max(axis=1)
    correct = predictions == labels
    one_hot = np.eye(CLASS_COUNT, dtype=np.float64)[labels]
    counts = np.bincount(labels, minlength=CLASS_COUNT)
    adaptive_ece = 0.0
    for indexes in np.array_split(np.argsort(confidences), bins):
        adaptive_ece += (
            len(indexes)
            / len(labels)
            * abs(float(confidences[indexes].mean()) - float(correct[indexes].mean()))
        )

    classwise_ece: list[float] = []
    per_class: list[dict[str, object]] = []
    for action_index in range(CLASS_COUNT):
        truth = labels == action_index
        predicted_as_class = predictions == action_index
        support = int(truth.sum())
        predicted_count = int(predicted_as_class.sum())
        true_positive = int((truth & predicted_as_class).sum())
        class_ece = 0.0
        for bin_index in range(bins):
            lower = bin_index / bins
            upper = (bin_index + 1) / bins
            members = (observed[:, action_index] >= lower) & (
                observed[:, action_index] < (upper if bin_index < bins - 1 else 1.0000001)
            )
            if members.any():
                class_ece += float(members.mean()) * abs(
                    float(observed[members, action_index].mean()) - float(truth[members].mean())
                )
        classwise_ece.append(class_ece)
        per_class.append(
            {
                "action_index": action_index,
                "support": support,
                "predicted": predicted_count,
                "precision": true_positive / predicted_count if predicted_count else None,
                "recall": true_positive / support if support else None,
                "mean_probability": float(observed[:, action_index].mean()),
                "maximum_probability": float(observed[:, action_index].max()),
                "classwise_ece": class_ece,
            }
        )

    unsupported = np.flatnonzero(counts == 0)
    unsupported_mass = (
        observed[:, unsupported].sum(axis=1)
        if len(unsupported)
        else np.zeros(len(labels), dtype=np.float64)
    )
    present_recalls = [
        float(item["recall"]) for item in per_class if isinstance(item["recall"], (int, float))
    ]
    return {
        "multiclass_brier_score": float(np.mean(np.sum((observed - one_hot) ** 2, axis=1))),
        "adaptive_ece_equal_frequency": adaptive_ece,
        "mean_classwise_ece_all_classes": float(np.mean(classwise_ece)),
        "mean_classwise_ece_present_classes": float(
            np.mean([classwise_ece[index] for index, count in enumerate(counts) if count > 0])
        ),
        "accuracy": float(correct.mean()),
        "mean_confidence": float(confidences.mean()),
        "confidence_minus_accuracy": float(confidences.mean() - correct.mean()),
        "macro_recall_present_classes": float(np.mean(present_recalls)),
        "majority_class_accuracy_baseline": float(counts.max() / len(labels)),
        "three_most_frequent_classes_top3_baseline": float(
            np.sort(counts)[-3:].sum() / len(labels)
        ),
        "unsupported_target_classes": unsupported.tolist(),
        "unsupported_classes_mean_total_probability": float(unsupported_mass.mean()),
        "unsupported_classes_max_total_probability": float(unsupported_mass.max(initial=0.0)),
        "unsupported_classes_modal_predictions": int(np.isin(predictions, unsupported).sum()),
        "per_class": per_class,
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def stable_split_id(observation: Observation) -> str:
    """Frozen semantic-state identity, independent of labels and tensor layout."""

    ranks = "23456789TJQKA"
    suits = "shdc"
    zones = (
        observation.hole,
        observation.board[:3],
        observation.board[3:4],
        observation.board[4:5],
    )
    signatures: dict[str, tuple[int, int, int, int]] = {}
    for suit in suits:
        masks: list[int] = []
        for zone in zones:
            mask = 0
            for card in zone:
                text = str(card)
                if text[1] == suit:
                    mask |= 1 << ranks.index(text[0])
            masks.append(mask)
        signatures[suit] = tuple(masks)  # type: ignore[assignment]
    suit_mapping = {
        suit: canonical
        for canonical, suit in enumerate(sorted(suits, key=lambda suit: (signatures[suit], suit)))
    }

    def canonical_card(card: object) -> int:
        text = str(card)
        return suit_mapping[text[1]] * 13 + ranks.index(text[0])

    n = len(observation.players)
    players = sorted(
        observation.players,
        key=lambda player: (player.seat - observation.seat) % n,
    )
    canonical_input = {
        "hole": sorted(canonical_card(card) for card in observation.hole),
        "flop": sorted(canonical_card(card) for card in observation.board[:3]),
        "turn": [canonical_card(card) for card in observation.board[3:4]],
        "river": [canonical_card(card) for card in observation.board[4:5]],
        "pot": observation.pot,
        "to_call": observation.to_call,
        "current_bet": observation.current_bet,
        "min_raise_to": observation.min_raise_to,
        "legal_actions": sorted(action.value for action in observation.legal_actions),
        "num_active": observation.num_active,
        "players": [
            {
                "relative_seat": relative,
                "stack": player.stack,
                "current_bet": player.current_bet,
                "total_committed": player.total_committed,
                "status": player.status,
                "is_button": player.is_button,
            }
            for relative, player in enumerate(players)
        ],
        "history": [
            {
                "relative_seat": (
                    "unknown" if event.seat == -1 else (event.seat - observation.seat) % n
                ),
                "street": event.street,
                "action": event.action,
                "amount_added": event.amount_added,
                "raise_to": event.raise_to,
                "pot_before": event.pot_before,
                "to_call_before": event.to_call_before,
                "is_full_raise": event.is_full_raise,
                "is_forced": event.is_forced,
            }
            for event in observation.history
        ],
    }
    payload = json.dumps(
        {"contract": "pokerbench-semantic-split-v1", "input": canonical_input},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def compressed_features(encoded: EncodedObservationV2) -> np.ndarray:
    """Flatten the complete bounded sequence; no temporal pooling or order collision."""

    history = np.asarray(encoded.history, dtype=np.float32)
    history_mask_values = np.asarray(encoded.history_mask, dtype=np.float32)
    legal_mask_values = np.asarray(encoded.legal_mask, dtype=np.float32)
    if (
        not np.isin(history_mask_values, (0.0, 1.0)).all()
        or not np.isin(legal_mask_values, (0.0, 1.0)).all()
    ):
        raise ValueError("Expert v2 masks must be exactly binary")
    if np.any(np.diff(history_mask_values) > 0.0):
        raise ValueError("Expert v2 history mask must be a contiguous one-prefix")
    if np.any(history[history_mask_values == 0.0] != 0.0):
        raise ValueError("Expert v2 padded history rows must be exactly zero")
    history_mask = history_mask_values.reshape(MAX_HISTORY, 1)
    ordered_history = history * history_mask
    result = np.concatenate(
        (
            np.asarray(encoded.cards, dtype=np.float32),
            np.asarray(encoded.global_features, dtype=np.float32),
            np.asarray(encoded.seats, dtype=np.float32).reshape(-1),
            ordered_history.reshape(-1),
            legal_mask_values,
        )
    )
    if (
        result.shape != (COMPRESSED_FEATURES,)
        or not np.isfinite(result).all()
        or np.any(result < 0.0)
        or np.any(result > 1.0)
    ):
        raise ValueError("Expert v2 compressed feature contract is invalid")
    return result


def internal_validation_member(group_id: str) -> bool:
    """Frozen 10% state-group split; published test files are never consulted."""

    if len(group_id) != 64 or any(character not in "0123456789abcdef" for character in group_id):
        raise ValueError("validation group id must be a lowercase SHA-256 digest")
    payload = f"poker-arena-v2-validation:{group_id}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % 10 == 0


def sealed_final_holdout_member(group_id: str) -> bool:
    """Frozen 5% acceptance partition; it must not be scored during iteration."""

    if len(group_id) != 64 or any(character not in "0123456789abcdef" for character in group_id):
        raise ValueError("sealed holdout group id must be a lowercase SHA-256 digest")
    payload = f"poker-arena-v2-sealed-final-holdout-2026-08-08:{group_id}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % 20 == 0


def internal_calibration_member(group_id: str) -> bool:
    """Frozen 10% group assignment used only after model/seed selection."""

    if len(group_id) != 64 or any(character not in "0123456789abcdef" for character in group_id):
        raise ValueError("calibration group id must be a lowercase SHA-256 digest")
    payload = f"poker-arena-v2-calibration-2026-08-08:{group_id}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % 10 == 0


def internal_calibration_check_member(group_id: str) -> bool:
    """Frozen half of calibration groups, never used to fit the temperature."""

    if len(group_id) != 64 or any(character not in "0123456789abcdef" for character in group_id):
        raise ValueError("calibration-check group id must be a lowercase SHA-256 digest")
    payload = f"poker-arena-v2-calibration-check-2026-08-08:{group_id}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % 2 == 0


def decontaminated_split(
    training_split_ids: np.ndarray,
    training_group_ids: np.ndarray,
    published_test_group_ids: np.ndarray,
) -> DecontaminatedSplit:
    """Exclude every exact published-test group before making the internal split."""

    if (
        training_split_ids.ndim != 1
        or training_group_ids.ndim != 1
        or published_test_group_ids.ndim != 1
        or len(training_split_ids) != len(training_group_ids)
    ):
        raise ValueError("group id collections must be one-dimensional")
    test_groups = {str(group_id) for group_id in published_test_group_ids}
    overlap_mask = np.fromiter(
        (str(group_id) in test_groups for group_id in training_group_ids),
        dtype=np.bool_,
        count=len(training_group_ids),
    )
    validation_assignment = np.fromiter(
        (internal_validation_member(str(split_id)) for split_id in training_split_ids),
        dtype=np.bool_,
        count=len(training_group_ids),
    )
    eligible = ~overlap_mask
    sealed_assignment = np.fromiter(
        (sealed_final_holdout_member(str(split_id)) for split_id in training_split_ids),
        dtype=np.bool_,
        count=len(training_group_ids),
    )
    sealed_final_holdout_mask = eligible & sealed_assignment
    development_eligible = eligible & ~sealed_final_holdout_mask
    calibration_assignment = np.fromiter(
        (internal_calibration_member(str(split_id)) for split_id in training_split_ids),
        dtype=np.bool_,
        count=len(training_group_ids),
    )
    calibration_check_assignment = np.fromiter(
        (internal_calibration_check_member(str(split_id)) for split_id in training_split_ids),
        dtype=np.bool_,
        count=len(training_group_ids),
    )
    calibration_check_mask = (
        development_eligible & calibration_assignment & calibration_check_assignment
    )
    calibration_mask = development_eligible & calibration_assignment & ~calibration_check_assignment
    validation_mask = development_eligible & ~calibration_assignment & validation_assignment
    training_mask = development_eligible & ~calibration_assignment & ~validation_assignment
    if (
        not training_mask.any()
        or not validation_mask.any()
        or not calibration_mask.any()
        or not calibration_check_mask.any()
        or not sealed_final_holdout_mask.any()
    ):
        raise ValueError("decontaminated train/validation/calibration split is degenerate")
    training_groups = {str(group_id) for group_id in training_group_ids[training_mask]}
    validation_groups = {str(group_id) for group_id in training_group_ids[validation_mask]}
    calibration_groups = {str(group_id) for group_id in training_group_ids[calibration_mask]}
    calibration_check_groups = {
        str(group_id) for group_id in training_group_ids[calibration_check_mask]
    }
    sealed_groups = {str(group_id) for group_id in training_group_ids[sealed_final_holdout_mask]}
    if (
        training_groups & validation_groups
        or training_groups & calibration_groups
        or training_groups & sealed_groups
        or training_groups & calibration_check_groups
        or validation_groups & calibration_groups
        or validation_groups & calibration_check_groups
        or validation_groups & sealed_groups
        or calibration_groups & calibration_check_groups
        or calibration_groups & sealed_groups
        or calibration_check_groups & sealed_groups
        or (
            training_groups
            | validation_groups
            | calibration_groups
            | calibration_check_groups
            | sealed_groups
        )
        & test_groups
    ):
        raise ValueError("decontaminated split retained a forbidden group overlap")
    return DecontaminatedSplit(
        training_mask=training_mask,
        validation_mask=validation_mask,
        calibration_mask=calibration_mask,
        calibration_check_mask=calibration_check_mask,
        sealed_final_holdout_mask=sealed_final_holdout_mask,
        overlap_example_count=int(overlap_mask.sum()),
        overlap_group_count=len({str(group_id) for group_id in training_group_ids[overlap_mask]}),
    )


def group_label_audit(group_ids: np.ndarray, targets: np.ndarray) -> dict[str, int | float]:
    """Measure duplicate-label consistency and the exact-feature top-1 ceiling."""

    if group_ids.ndim != 1 or targets.ndim != 1 or len(group_ids) != len(targets):
        raise ValueError("group label audit requires aligned one-dimensional arrays")
    if not len(targets):
        raise ValueError("group label audit requires at least one example")
    if (
        not np.issubdtype(targets.dtype, np.integer)
        or np.any(targets < 0)
        or np.any(targets >= CLASS_COUNT)
    ):
        raise ValueError("group label audit requires valid integer class targets")
    labels_by_group: defaultdict[str, Counter[int]] = defaultdict(Counter)
    for group_id, target in zip(group_ids, targets, strict=True):
        labels_by_group[str(group_id)][int(target)] += 1
    conflicting = [counts for counts in labels_by_group.values() if len(counts) > 1]
    maximum_correct = sum(max(counts.values()) for counts in labels_by_group.values())
    return {
        "examples": len(targets),
        "unique_groups": len(labels_by_group),
        "duplicate_examples": len(targets) - len(labels_by_group),
        "conflicting_groups": len(conflicting),
        "examples_in_conflicting_groups": sum(sum(counts.values()) for counts in conflicting),
        "exact_feature_top1_ceiling": maximum_correct / len(targets),
    }


def prepare_csv_files(
    files: list[tuple[str, Path]],
    *,
    reject_ambiguous: bool = True,
    redact_split_member: Callable[[str], bool] | None = None,
) -> PreparedDataset:
    features: list[np.ndarray] = []
    targets: list[int] = []
    source_keys: list[str] = []
    row_numbers: list[int] = []
    group_ids: list[str] = []
    split_ids: list[str] = []
    contexts: list[tuple[int, int, int, int, int, int, int]] = []
    positions: list[str] = []
    history_audits: list[tuple[int, int, int, int, int, int, int, int, int]] = []
    source_audit: list[tuple[str, int, int, int, int]] = []
    rows_seen = failures = ambiguous = 0
    for source_key, path in files:
        if source_key not in POKERBENCH_FILES:
            raise ValueError(f"unknown PokerBench source key: {source_key!r}")
        expected_name, expected_sha = POKERBENCH_FILES[source_key]
        if path.name != expected_name or sha256_file(path) != expected_sha:
            raise ValueError(f"PokerBench source {source_key!r} failed identity verification")
        source_rows = source_eligible = source_failures = source_ambiguous = 0
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or len(reader.fieldnames) != len(set(reader.fieldnames)):
                raise ValueError("PokerBench CSV header is absent or duplicated")
            for row_number, row in enumerate(reader):
                rows_seen += 1
                source_rows += 1
                try:
                    inputs = featurize_v2_input(dict(row))
                    feature_row = compressed_features(inputs.encoded)
                    group_id = hashlib.sha256(feature_row.tobytes()).hexdigest()
                    split_id = stable_split_id(inputs.observation)
                except (KeyError, StopIteration, TypeError, ValueError):
                    failures += 1
                    source_failures += 1
                    continue
                # Redaction and decontaminated_split must use the same frozen semantic
                # identity. The encoder feature hash is a separate leakage identity.
                if redact_split_member is not None and redact_split_member(split_id):
                    target = -1
                else:
                    try:
                        target, _error, mapping_ambiguous = target_v2(dict(row), inputs.observation)
                    except (KeyError, StopIteration, TypeError, ValueError):
                        failures += 1
                        source_failures += 1
                        continue
                    if mapping_ambiguous:
                        ambiguous += 1
                        source_ambiguous += 1
                        if reject_ambiguous:
                            continue
                observation = inputs.observation
                street_code = {0: 0, 3: 1, 4: 2, 5: 3}[len(observation.board)]
                features.append(feature_row)
                targets.append(target)
                source_keys.append(source_key)
                row_numbers.append(row_number)
                group_ids.append(group_id)
                split_ids.append(split_id)
                contexts.append(
                    (
                        street_code,
                        observation.seat,
                        len(observation.players),
                        int(sum(inputs.encoded.legal_mask)),
                        observation.pot,
                        observation.to_call,
                        len(observation.history),
                    )
                )
                positions.append(observation.players[observation.seat].name)
                audit = inputs.history_audit
                history_audits.append(
                    (
                        audit.raw_lines,
                        audit.expected_action_tokens,
                        audit.emitted_action_events,
                        audit.forced_events,
                        audit.ignored_action_tokens,
                        audit.unknown_actor_events,
                        audit.dealt_cards,
                        audit.reconstructed_pot_units,
                        audit.reported_pot_units,
                    )
                )
                source_eligible += 1
        source_audit.append(
            (
                source_key,
                source_rows,
                source_eligible,
                source_failures,
                source_ambiguous,
            )
        )
    if not features:
        raise ValueError("PokerBench preparation produced no eligible examples")
    return PreparedDataset(
        features=np.stack(features),
        targets=np.asarray(targets, dtype=np.int64),
        source_keys=np.asarray(source_keys),
        row_numbers=np.asarray(row_numbers, dtype=np.int64),
        group_ids=np.asarray(group_ids),
        split_ids=np.asarray(split_ids),
        context=np.asarray(contexts, dtype=np.int64),
        positions=np.asarray(positions),
        history_audit=np.asarray(history_audits, dtype=np.int64),
        source_audit=tuple(source_audit),
        rows_seen=rows_seen,
        parse_failures=failures,
        ambiguous_sizing=ambiguous,
    )
