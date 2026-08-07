from scripts.power_analysis import designs, wilson_bound


def test_power_analysis_reproduces_the_policy_sample_floors() -> None:
    result = designs()

    assert result["exact_state"].samples == 99
    assert result["false_accept"].samples == 142
    assert result["subgroup_exact_state"].samples == 40
    assert all(design.type_one_error <= 0.05 for design in result.values())
    assert all(design.power >= 0.80 for design in result.values())


def test_wilson_bound_is_bounded() -> None:
    assert 0 <= wilson_bound(0, 100, upper=False) <= 1
    assert 0 <= wilson_bound(100, 100, upper=True) <= 1
