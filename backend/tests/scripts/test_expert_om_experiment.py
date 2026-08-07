import hashlib
import json

import pytest

from scripts.expert_om_experiment import load_preregistration, paired, promotion_verdict

POWER_RECEIPT = "sha256:" + "a" * 64


def _ci(lo: float, hi: float) -> dict[str, object]:
    return {
        "lo": lo,
        "hi": hi,
        "n_blocks": 30,
        "block_unit": "independent_reset_match_block",
        "familywise_alpha": 0.05 / 6,
    }


def _with_ids(groups: dict[str, list[dict[str, object]]]) -> dict[str, list[dict[str, object]]]:
    for group, intervals in groups.items():
        for index, interval in enumerate(intervals):
            interval["group"] = group
            interval["comparison_id"] = f"{group.lower()}-{index}"
    return groups


def test_noninferiority_uses_lower_confidence_bound():
    groups = _with_ids(
        {
            "EXPLORAVEL": [_ci(1, 3), _ci(2, 4), _ci(-1, 2)],
            # hi > -5 would incorrectly pass, but lo=-12 disproves non-inferiority.
            "ROBUSTO": [_ci(-12, 1), _ci(-2, 2)],
            "CONTROLE": [_ci(-1, 3)],
        }
    )
    verdict = promotion_verdict(
        groups,
        noninferiority_margin=5.0,
        power_analysis_id=POWER_RECEIPT,
        minimum_detectable_effect=20.0,
        control_equivalence_margin=5.0,
    )
    assert verdict["explorable_gain"] is True
    assert verdict["robust_noninferior"] is False
    assert verdict["promote"] is False


def test_control_red_flag_blocks_promotion():
    groups = _with_ids(
        {
            "EXPLORAVEL": [_ci(1, 3), _ci(2, 4), _ci(1, 2)],
            "ROBUSTO": [_ci(-2, 2), _ci(-4, 1)],
            "CONTROLE": [_ci(6, 9)],
        }
    )
    verdict = promotion_verdict(
        groups,
        noninferiority_margin=5.0,
        power_analysis_id=POWER_RECEIPT,
        minimum_detectable_effect=10.0,
        control_equivalence_margin=5.0,
    )
    assert verdict["control_ok"] is False
    assert verdict["promote"] is False


def test_missing_preregistration_blocks_promotion_even_when_intervals_look_good():
    groups = _with_ids(
        {
            "EXPLORAVEL": [_ci(1, 2), _ci(2, 3), _ci(1, 3)],
            "ROBUSTO": [_ci(0.1, 1), _ci(0.2, 1)],
            "CONTROLE": [_ci(-1, 1)],
        }
    )
    verdict = promotion_verdict(groups)
    assert verdict["design_preregistered"] is False
    assert verdict["precision_supports_mde"] is False
    assert verdict["promote"] is False


def test_declared_mde_is_enforced_as_precision_gate():
    groups = _with_ids(
        {
            "EXPLORAVEL": [_ci(1, 8), _ci(2, 9), _ci(1, 8)],
            "ROBUSTO": [_ci(0.1, 7), _ci(0.2, 7)],
            "CONTROLE": [_ci(-1, 1)],
        }
    )
    verdict = promotion_verdict(
        groups,
        noninferiority_margin=0.0,
        power_analysis_id=POWER_RECEIPT,
        minimum_detectable_effect=2.0,
        control_equivalence_margin=5.0,
    )
    assert verdict["design_preregistered"] is True
    assert verdict["precision_supports_mde"] is False
    assert verdict["promote"] is False


def test_fully_preregistered_precise_design_can_pass():
    groups = _with_ids(
        {
            "EXPLORAVEL": [_ci(1, 2), _ci(2, 3), _ci(1, 3)],
            "ROBUSTO": [_ci(0.1, 1), _ci(0.2, 1)],
            "CONTROLE": [_ci(-1, 1)],
        }
    )
    verdict = promotion_verdict(
        groups,
        noninferiority_margin=0.0,
        power_analysis_id=POWER_RECEIPT,
        minimum_detectable_effect=1.0,
        control_equivalence_margin=2.0,
    )
    assert verdict["design_preregistered"] is True
    assert verdict["precision_supports_mde"] is True
    assert verdict["promote"] is True


def test_unblocked_or_unadjusted_intervals_fail_closed():
    groups = _with_ids(
        {
            "EXPLORAVEL": [_ci(1, 2), _ci(2, 3), _ci(1, 3)],
            "ROBUSTO": [_ci(0.1, 1), _ci(0.2, 1)],
            "CONTROLE": [_ci(-1, 1)],
        }
    )
    groups["ROBUSTO"][0]["n_blocks"] = 29
    groups["CONTROLE"][0]["familywise_alpha"] = 0.05
    verdict = promotion_verdict(
        groups,
        noninferiority_margin=0.0,
        power_analysis_id=POWER_RECEIPT,
        minimum_detectable_effect=1.0,
        control_equivalence_margin=2.0,
    )
    assert verdict["intervals_valid"] is False
    assert verdict["promote"] is False


def test_paired_uses_required_blocks_and_familywise_alpha():
    base = [0.0] * 60
    candidate = [0.1] * 60
    result = paired(base, candidate, required_blocks=30, familywise_comparisons=6)
    assert result["n_blocks"] == 30
    assert result["familywise_alpha"] == pytest.approx(0.05 / 6)
    assert result["block_unit"] == "independent_reset_match_block"


def test_paired_rejects_too_few_hands_for_block_design():
    with pytest.raises(ValueError, match="at least 30 hands"):
        paired([0.0] * 29, [0.1] * 29)


def test_group_contract_requires_exact_cardinality_and_unique_ids():
    groups = _with_ids(
        {
            "EXPLORAVEL": [_ci(1, 2), _ci(2, 3), _ci(1, 3)],
            "ROBUSTO": [_ci(0, 1), _ci(0, 1)],
            "CONTROLE": [_ci(-1, 1)],
        }
    )
    groups["ROBUSTO"][1]["comparison_id"] = groups["ROBUSTO"][0]["comparison_id"]
    verdict = promotion_verdict(
        groups,
        noninferiority_margin=0.0,
        power_analysis_id=POWER_RECEIPT,
        minimum_detectable_effect=1.0,
        control_equivalence_margin=2.0,
    )
    assert verdict["group_contract_valid"] is False
    assert verdict["promote"] is False


def test_free_text_power_id_is_not_a_preregistration_receipt():
    groups = _with_ids(
        {
            "EXPLORAVEL": [_ci(1, 2), _ci(2, 3), _ci(1, 3)],
            "ROBUSTO": [_ci(0, 1), _ci(0, 1)],
            "CONTROLE": [_ci(-1, 1)],
        }
    )
    verdict = promotion_verdict(
        groups,
        noninferiority_margin=0.0,
        power_analysis_id="created-after-results",
        minimum_detectable_effect=1.0,
        control_equivalence_margin=2.0,
    )
    assert verdict["design_preregistered"] is False
    assert verdict["promote"] is False


def test_preregistration_receipt_is_closed_and_content_addressed(tmp_path):
    payload = {
        "schema_version": 1,
        "experiment_id": "expert-om-v3",
        "frozen_reference": "registry:expert-om-v3-20260717",
        "power_analysis_reference": "power:expert-om-v3-20260717",
        "minimum_detectable_effect_bb100": 10.0,
        "noninferiority_margin_bb100": 5.0,
        "control_equivalence_margin_bb100": 2.0,
        "family_size": 6,
        "required_blocks": 30,
        "block_unit": "independent_reset_match_block",
    }
    path = tmp_path / "prereg.json"
    raw = json.dumps(payload, sort_keys=True).encode()
    path.write_bytes(raw)
    parsed, receipt_id = load_preregistration(path)
    assert parsed == payload
    assert receipt_id == "sha256:" + hashlib.sha256(raw).hexdigest()


def test_preregistration_duplicate_key_fails_closed(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate key"):
        load_preregistration(path)
