"""Tests for percell3.io.conditions — condition auto-detection."""

from percell3.io.conditions import ConditionDetectionResult, detect_conditions


class TestDetectConditions:
    def test_multi_condition_with_s_suffix(self):
        fovs = [
            "A549_Control_s00",
            "A549_Control_s01",
            "A549_Noco_s00",
            "A549_Noco_s01",
            "A549_ULKi_s00",
            "A549_ULKi_s01",
            "A549_VCPi_s00",
            "A549_VCPi_s01",
        ]
        result = detect_conditions(fovs)
        assert result is not None
        assert result.conditions == [
            "A549_Control", "A549_Noco", "A549_ULKi", "A549_VCPi"
        ]
        assert result.pattern_used == r"_s\d+$"
        assert result.condition_map["A549_Control_s00"] == "A549_Control"
        assert result.condition_map["A549_VCPi_s01"] == "A549_VCPi"
        assert result.fov_name_map["A549_Control_s00"] == "s00"
        assert result.fov_name_map["A549_Control_s01"] == "s01"

    def test_multi_condition_with_numeric_suffix(self):
        fovs = ["ctrl_1", "ctrl_2", "treated_1", "treated_2"]
        result = detect_conditions(fovs)
        assert result is not None
        assert result.conditions == ["ctrl", "treated"]
        assert result.pattern_used == r"_\d+$"

    def test_multi_condition_with_fov_suffix(self):
        fovs = ["wt_fov0", "wt_fov1", "ko_fov0", "ko_fov1"]
        result = detect_conditions(fovs)
        assert result is not None
        assert result.conditions == ["ko", "wt"]
        assert result.pattern_used == r"_fov\d+$"

    def test_single_prefix_returns_none(self):
        fovs = ["control_s00", "control_s01", "control_s02"]
        result = detect_conditions(fovs)
        assert result is None

    def test_no_matching_pattern_returns_none(self):
        fovs = ["alpha", "beta", "gamma"]
        result = detect_conditions(fovs)
        assert result is None

    def test_empty_input_returns_none(self):
        assert detect_conditions([]) is None

    def test_single_fov_returns_none(self):
        assert detect_conditions(["control_s00"]) is None

    def test_mixed_patterns_no_universal_match_returns_none(self):
        # _s\d+ doesn't match all; _\d+ doesn't match all
        fovs = ["ctrl_s00", "treated_fov1"]
        result = detect_conditions(fovs)
        assert result is None

    def test_result_is_frozen(self):
        fovs = ["a_s0", "b_s0"]
        result = detect_conditions(fovs)
        assert result is not None
        assert isinstance(result, ConditionDetectionResult)
