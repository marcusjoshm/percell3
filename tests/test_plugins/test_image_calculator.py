"""Tests for ImageCalculatorPlugin and image_calculator_core."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from percell3.core import ExperimentStore
from percell3.plugins.builtin.image_calculator import ImageCalculatorPlugin
from percell3.plugins.builtin.image_calculator_core import (
    OPERATIONS,
    _get_dtype_range,
    apply_single_channel,
    apply_two_channel,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def calculator_experiment(tmp_path):
    """Create a minimal experiment with known pixel values for testing.

    Layout:
        - 3 channels: ch00, ch01, ch02
        - 1 FOV (64x64), condition "control"
        - ch00: uniform 100 (uint16)
        - ch01: uniform 50 (uint16)
        - ch02: uniform 200 (uint16)

    Yields:
        (store, fov_id) tuple.
    """
    store = ExperimentStore.create(tmp_path / "calc_test.percell")
    store.add_channel("ch00")
    store.add_channel("ch01")
    store.add_channel("ch02")
    store.add_condition("control")

    fov_id = store.add_fov("control", width=64, height=64, pixel_size_um=0.65)

    ch00 = np.full((64, 64), 100, dtype=np.uint16)
    ch01 = np.full((64, 64), 50, dtype=np.uint16)
    ch02 = np.full((64, 64), 200, dtype=np.uint16)

    store.write_image(fov_id, "ch00", ch00)
    store.write_image(fov_id, "ch01", ch01)
    store.write_image(fov_id, "ch02", ch02)

    yield store, fov_id
    store.close()


# ---------------------------------------------------------------------------
# Core math tests
# ---------------------------------------------------------------------------


class TestApplySingleChannel:
    """Tests for apply_single_channel (pure numpy)."""

    def test_add(self):
        img = np.full((4, 4), 100, dtype=np.uint16)
        result = apply_single_channel(img, "add", 50)
        assert result.dtype == np.uint16
        assert np.all(result == 150)

    def test_subtract(self):
        img = np.full((4, 4), 100, dtype=np.uint16)
        result = apply_single_channel(img, "subtract", 30)
        assert np.all(result == 70)

    def test_multiply(self):
        img = np.full((4, 4), 100, dtype=np.uint16)
        result = apply_single_channel(img, "multiply", 3)
        assert np.all(result == 300)

    def test_divide(self):
        img = np.full((4, 4), 100, dtype=np.uint16)
        result = apply_single_channel(img, "divide", 4)
        assert np.all(result == 25)

    def test_min(self):
        img = np.full((4, 4), 100, dtype=np.uint16)
        result = apply_single_channel(img, "min", 80)
        assert np.all(result == 80)

    def test_max(self):
        img = np.full((4, 4), 100, dtype=np.uint16)
        result = apply_single_channel(img, "max", 200)
        assert np.all(result == 200)

    def test_abs_diff(self):
        img = np.full((4, 4), 100, dtype=np.uint16)
        result = apply_single_channel(img, "abs_diff", 130)
        assert np.all(result == 30)

    def test_and(self):
        img = np.full((4, 4), 0xFF, dtype=np.uint16)
        result = apply_single_channel(img, "and", 0x0F)
        assert np.all(result == 0x0F)

    def test_or(self):
        img = np.full((4, 4), 0xF0, dtype=np.uint16)
        result = apply_single_channel(img, "or", 0x0F)
        assert np.all(result == 0xFF)

    def test_xor(self):
        img = np.full((4, 4), 0xFF, dtype=np.uint16)
        result = apply_single_channel(img, "xor", 0xFF)
        assert np.all(result == 0)

    def test_overflow_clips_to_max(self):
        img = np.full((4, 4), 65500, dtype=np.uint16)
        result = apply_single_channel(img, "add", 100)
        assert result.dtype == np.uint16
        assert np.all(result == 65535)

    def test_underflow_clips_to_zero(self):
        img = np.full((4, 4), 10, dtype=np.uint16)
        result = apply_single_channel(img, "subtract", 100)
        assert result.dtype == np.uint16
        assert np.all(result == 0)

    def test_divide_by_zero(self):
        img = np.full((4, 4), 100, dtype=np.uint16)
        result = apply_single_channel(img, "divide", 0)
        assert np.all(result == 0)

    def test_unknown_operation_raises(self):
        img = np.full((4, 4), 100, dtype=np.uint16)
        with pytest.raises(ValueError, match="Unknown operation"):
            apply_single_channel(img, "power", 2)

    def test_preserves_uint8_dtype(self):
        img = np.full((4, 4), 100, dtype=np.uint8)
        result = apply_single_channel(img, "add", 200)
        assert result.dtype == np.uint8
        assert np.all(result == 255)  # clipped

    def test_float32_input_dtype(self):
        img = np.full((4, 4), 1.5, dtype=np.float32)
        result = apply_single_channel(img, "add", 0.5)
        assert result.dtype == np.float32
        np.testing.assert_allclose(result, 2.0)


class TestApplyTwoChannel:
    """Tests for apply_two_channel (pure numpy)."""

    def test_add(self):
        a = np.full((4, 4), 100, dtype=np.uint16)
        b = np.full((4, 4), 50, dtype=np.uint16)
        result = apply_two_channel(a, b, "add")
        assert result.dtype == np.uint16
        assert np.all(result == 150)

    def test_subtract(self):
        a = np.full((4, 4), 100, dtype=np.uint16)
        b = np.full((4, 4), 30, dtype=np.uint16)
        result = apply_two_channel(a, b, "subtract")
        assert np.all(result == 70)

    def test_multiply(self):
        a = np.full((4, 4), 100, dtype=np.uint16)
        b = np.full((4, 4), 5, dtype=np.uint16)
        result = apply_two_channel(a, b, "multiply")
        assert np.all(result == 500)

    def test_divide(self):
        a = np.full((4, 4), 100, dtype=np.uint16)
        b = np.full((4, 4), 4, dtype=np.uint16)
        result = apply_two_channel(a, b, "divide")
        assert np.all(result == 25)

    def test_divide_by_zero_pixels(self):
        a = np.full((4, 4), 100, dtype=np.uint16)
        b = np.zeros((4, 4), dtype=np.uint16)
        result = apply_two_channel(a, b, "divide")
        assert np.all(result == 0)

    def test_abs_diff(self):
        a = np.full((4, 4), 50, dtype=np.uint16)
        b = np.full((4, 4), 120, dtype=np.uint16)
        result = apply_two_channel(a, b, "abs_diff")
        assert np.all(result == 70)

    def test_min(self):
        a = np.full((4, 4), 100, dtype=np.uint16)
        b = np.full((4, 4), 50, dtype=np.uint16)
        result = apply_two_channel(a, b, "min")
        assert np.all(result == 50)

    def test_max(self):
        a = np.full((4, 4), 100, dtype=np.uint16)
        b = np.full((4, 4), 200, dtype=np.uint16)
        result = apply_two_channel(a, b, "max")
        assert np.all(result == 200)

    def test_overflow_clips(self):
        a = np.full((4, 4), 60000, dtype=np.uint16)
        b = np.full((4, 4), 60000, dtype=np.uint16)
        result = apply_two_channel(a, b, "add")
        assert np.all(result == 65535)

    def test_output_dtype_follows_image_a(self):
        a = np.full((4, 4), 100, dtype=np.uint8)
        b = np.full((4, 4), 50, dtype=np.uint16)
        result = apply_two_channel(a, b, "add")
        assert result.dtype == np.uint8
        assert np.all(result == 150)

    def test_shape_mismatch_raises(self):
        a = np.full((4, 4), 100, dtype=np.uint16)
        b = np.full((4, 8), 50, dtype=np.uint16)
        with pytest.raises(ValueError, match="Shape mismatch"):
            apply_two_channel(a, b, "add")

    def test_bitwise_and(self):
        a = np.full((4, 4), 0xFF, dtype=np.uint16)
        b = np.full((4, 4), 0x0F, dtype=np.uint16)
        result = apply_two_channel(a, b, "and")
        assert np.all(result == 0x0F)


# ---------------------------------------------------------------------------
# _get_dtype_range tests
# ---------------------------------------------------------------------------


class TestGetDtypeRange:
    """Tests for _get_dtype_range guard."""

    def test_bool_dtype_raises(self):
        with pytest.raises(TypeError, match="Unsupported dtype"):
            _get_dtype_range(np.dtype(bool))

    def test_uint16_returns_range(self):
        lo, hi = _get_dtype_range(np.dtype(np.uint16))
        assert lo == 0.0
        assert hi == 65535.0

    def test_float64_returns_range(self):
        lo, hi = _get_dtype_range(np.dtype(np.float64))
        assert lo < 0
        assert hi > 0


# ---------------------------------------------------------------------------
# Plugin info / validation tests
# ---------------------------------------------------------------------------


class TestPluginInfo:
    """Tests for ImageCalculatorPlugin metadata."""

    def test_info(self):
        plugin = ImageCalculatorPlugin()
        info = plugin.info()
        assert info.name == "image_calculator"
        assert info.version == "1.0.0"

    def test_required_inputs_empty(self):
        plugin = ImageCalculatorPlugin()
        assert plugin.required_inputs() == []

    def test_parameter_schema_has_required_fields(self):
        plugin = ImageCalculatorPlugin()
        schema = plugin.get_parameter_schema()
        assert "mode" in schema["properties"]
        assert "operation" in schema["properties"]
        assert "fov_id" in schema["properties"]
        assert "channel_a" in schema["properties"]
        assert set(schema["required"]) == {"mode", "operation", "fov_id", "channel_a"}


class TestValidation:
    """Tests for ImageCalculatorPlugin.validate()."""

    def test_valid_experiment(self, calculator_experiment):
        store, _fov_id = calculator_experiment
        plugin = ImageCalculatorPlugin()
        errors = plugin.validate(store)
        assert errors == []

    def test_no_channels(self, tmp_path):
        store = ExperimentStore.create(tmp_path / "empty.percell")
        store.add_condition("ctrl")
        store.add_fov("ctrl", width=10, height=10)
        plugin = ImageCalculatorPlugin()
        errors = plugin.validate(store)
        assert any("channel" in e.lower() for e in errors)
        store.close()

    def test_no_fovs(self, tmp_path):
        store = ExperimentStore.create(tmp_path / "no_fovs.percell")
        store.add_channel("ch00")
        plugin = ImageCalculatorPlugin()
        errors = plugin.validate(store)
        assert any("fov" in e.lower() for e in errors)
        store.close()


# ---------------------------------------------------------------------------
# Single-channel plugin integration tests
# ---------------------------------------------------------------------------


class TestSingleChannelMath:
    """Integration tests: single_channel mode via plugin.run()."""

    def test_add_constant(self, calculator_experiment):
        store, fov_id = calculator_experiment
        plugin = ImageCalculatorPlugin()
        result = plugin.run(store, parameters={
            "mode": "single_channel",
            "operation": "add",
            "fov_id": fov_id,
            "channel_a": "ch00",
            "constant": 50,
        })

        assert result.measurements_written == 0
        derived_fov_id = int(result.custom_outputs["derived_fov_id"])

        # ch00 should be 100 + 50 = 150
        ch00 = store.read_image_numpy(derived_fov_id, "ch00")
        assert np.all(ch00 == 150)

        # ch01 and ch02 should be unchanged copies
        ch01 = store.read_image_numpy(derived_fov_id, "ch01")
        assert np.all(ch01 == 50)

        ch02 = store.read_image_numpy(derived_fov_id, "ch02")
        assert np.all(ch02 == 200)

    def test_multiply_constant(self, calculator_experiment):
        store, fov_id = calculator_experiment
        plugin = ImageCalculatorPlugin()
        result = plugin.run(store, parameters={
            "mode": "single_channel",
            "operation": "multiply",
            "fov_id": fov_id,
            "channel_a": "ch01",
            "constant": 3,
        })

        derived_fov_id = int(result.custom_outputs["derived_fov_id"])
        ch01 = store.read_image_numpy(derived_fov_id, "ch01")
        assert np.all(ch01 == 150)  # 50 * 3

    def test_missing_constant_raises(self, calculator_experiment):
        store, fov_id = calculator_experiment
        plugin = ImageCalculatorPlugin()
        with pytest.raises(RuntimeError, match="constant"):
            plugin.run(store, parameters={
                "mode": "single_channel",
                "operation": "add",
                "fov_id": fov_id,
                "channel_a": "ch00",
            })

    def test_nonfinite_constant_raises(self, calculator_experiment):
        store, fov_id = calculator_experiment
        plugin = ImageCalculatorPlugin()
        with pytest.raises(RuntimeError, match="finite"):
            plugin.run(store, parameters={
                "mode": "single_channel",
                "operation": "add",
                "fov_id": fov_id,
                "channel_a": "ch00",
                "constant": float("inf"),
            })

    def test_nan_constant_raises(self, calculator_experiment):
        store, fov_id = calculator_experiment
        plugin = ImageCalculatorPlugin()
        with pytest.raises(RuntimeError, match="finite"):
            plugin.run(store, parameters={
                "mode": "single_channel",
                "operation": "add",
                "fov_id": fov_id,
                "channel_a": "ch00",
                "constant": float("nan"),
            })

    def test_channel_a_not_found_raises(self, calculator_experiment):
        store, fov_id = calculator_experiment
        plugin = ImageCalculatorPlugin()
        with pytest.raises(RuntimeError, match="not found"):
            plugin.run(store, parameters={
                "mode": "single_channel",
                "operation": "add",
                "fov_id": fov_id,
                "channel_a": "nonexistent",
                "constant": 1,
            })


# ---------------------------------------------------------------------------
# Two-channel plugin integration tests
# ---------------------------------------------------------------------------


class TestTwoChannelMath:
    """Integration tests: two_channel mode via plugin.run()."""

    def test_add_channels(self, calculator_experiment):
        store, fov_id = calculator_experiment
        plugin = ImageCalculatorPlugin()
        result = plugin.run(store, parameters={
            "mode": "two_channel",
            "operation": "add",
            "fov_id": fov_id,
            "channel_a": "ch00",
            "channel_b": "ch01",
        })

        derived_fov_id = int(result.custom_outputs["derived_fov_id"])

        # ch00 = 100 + 50 = 150
        ch00 = store.read_image_numpy(derived_fov_id, "ch00")
        assert np.all(ch00 == 150)

        # ch01 should be zeroed (consumed)
        ch01 = store.read_image_numpy(derived_fov_id, "ch01")
        assert np.all(ch01 == 0)

        # ch02 should be copied unchanged
        ch02 = store.read_image_numpy(derived_fov_id, "ch02")
        assert np.all(ch02 == 200)

    def test_subtract_channels(self, calculator_experiment):
        store, fov_id = calculator_experiment
        plugin = ImageCalculatorPlugin()
        result = plugin.run(store, parameters={
            "mode": "two_channel",
            "operation": "subtract",
            "fov_id": fov_id,
            "channel_a": "ch00",
            "channel_b": "ch01",
        })

        derived_fov_id = int(result.custom_outputs["derived_fov_id"])
        ch00 = store.read_image_numpy(derived_fov_id, "ch00")
        assert np.all(ch00 == 50)  # 100 - 50

    def test_divide_channels(self, calculator_experiment):
        store, fov_id = calculator_experiment
        plugin = ImageCalculatorPlugin()
        result = plugin.run(store, parameters={
            "mode": "two_channel",
            "operation": "divide",
            "fov_id": fov_id,
            "channel_a": "ch00",
            "channel_b": "ch01",
        })

        derived_fov_id = int(result.custom_outputs["derived_fov_id"])
        ch00 = store.read_image_numpy(derived_fov_id, "ch00")
        assert np.all(ch00 == 2)  # 100 / 50

    def test_missing_channel_b_raises(self, calculator_experiment):
        store, fov_id = calculator_experiment
        plugin = ImageCalculatorPlugin()
        with pytest.raises(RuntimeError, match="channel_b"):
            plugin.run(store, parameters={
                "mode": "two_channel",
                "operation": "add",
                "fov_id": fov_id,
                "channel_a": "ch00",
            })

    def test_nonexistent_channel_raises(self, calculator_experiment):
        store, fov_id = calculator_experiment
        plugin = ImageCalculatorPlugin()
        with pytest.raises(RuntimeError, match="not found"):
            plugin.run(store, parameters={
                "mode": "two_channel",
                "operation": "add",
                "fov_id": fov_id,
                "channel_a": "ch00",
                "channel_b": "nonexistent",
            })

    def test_bitwise_and_two_channel(self, calculator_experiment):
        """Integration test for bitwise AND between two channels."""
        store, fov_id = calculator_experiment
        plugin = ImageCalculatorPlugin()
        result = plugin.run(store, parameters={
            "mode": "two_channel",
            "operation": "and",
            "fov_id": fov_id,
            "channel_a": "ch00",  # 100 = 0b01100100
            "channel_b": "ch01",  # 50  = 0b00110010
        })

        derived_fov_id = int(result.custom_outputs["derived_fov_id"])
        ch00 = store.read_image_numpy(derived_fov_id, "ch00")
        assert np.all(ch00 == (100 & 50))  # 32


# ---------------------------------------------------------------------------
# Derived FOV creation tests
# ---------------------------------------------------------------------------


class TestDerivedFOVCreation:
    """Tests for derived FOV naming, metadata, and idempotent re-runs."""

    def test_derived_fov_naming_single_channel(self, calculator_experiment):
        store, fov_id = calculator_experiment
        plugin = ImageCalculatorPlugin()
        plugin.run(store, parameters={
            "mode": "single_channel",
            "operation": "add",
            "fov_id": fov_id,
            "channel_a": "ch00",
            "constant": 50,
        })

        fov_names = [f.display_name for f in store.get_fovs()]
        # Should contain the original and the derived
        matching = [n for n in fov_names if "add" in n and "ch00" in n]
        assert len(matching) == 1

    def test_derived_fov_naming_two_channel(self, calculator_experiment):
        store, fov_id = calculator_experiment
        plugin = ImageCalculatorPlugin()
        plugin.run(store, parameters={
            "mode": "two_channel",
            "operation": "multiply",
            "fov_id": fov_id,
            "channel_a": "ch00",
            "channel_b": "ch01",
        })

        fov_names = [f.display_name for f in store.get_fovs()]
        matching = [n for n in fov_names if "multiply" in n and "ch01" in n]
        assert len(matching) == 1

    def test_derived_fov_inherits_metadata(self, calculator_experiment):
        store, fov_id = calculator_experiment
        plugin = ImageCalculatorPlugin()
        result = plugin.run(store, parameters={
            "mode": "single_channel",
            "operation": "add",
            "fov_id": fov_id,
            "channel_a": "ch00",
            "constant": 10,
        })

        derived_fov_id = int(result.custom_outputs["derived_fov_id"])
        original = store.get_fov_by_id(fov_id)
        derived = store.get_fov_by_id(derived_fov_id)

        assert derived.condition == original.condition
        assert derived.width == original.width
        assert derived.height == original.height
        assert derived.pixel_size_um == original.pixel_size_um

    def test_idempotent_rerun(self, calculator_experiment):
        store, fov_id = calculator_experiment
        plugin = ImageCalculatorPlugin()
        params = {
            "mode": "single_channel",
            "operation": "add",
            "fov_id": fov_id,
            "channel_a": "ch00",
            "constant": 50,
        }

        # First run
        result1 = plugin.run(store, parameters=params)
        fov_count_after_first = len(store.get_fovs())

        # Second run — should reuse existing derived FOV
        result2 = plugin.run(store, parameters=params)
        fov_count_after_second = len(store.get_fovs())

        assert fov_count_after_first == fov_count_after_second
        assert result1.custom_outputs["derived_fov_id"] == result2.custom_outputs["derived_fov_id"]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge case tests."""

    def test_same_channel_for_both_inputs(self, calculator_experiment):
        store, fov_id = calculator_experiment
        plugin = ImageCalculatorPlugin()
        result = plugin.run(store, parameters={
            "mode": "two_channel",
            "operation": "subtract",
            "fov_id": fov_id,
            "channel_a": "ch00",
            "channel_b": "ch00",
        })

        derived_fov_id = int(result.custom_outputs["derived_fov_id"])
        ch00 = store.read_image_numpy(derived_fov_id, "ch00")
        assert np.all(ch00 == 0)  # 100 - 100 = 0

    def test_progress_callback_called(self, calculator_experiment):
        store, fov_id = calculator_experiment
        plugin = ImageCalculatorPlugin()
        callback = MagicMock()

        plugin.run(store, parameters={
            "mode": "single_channel",
            "operation": "add",
            "fov_id": fov_id,
            "channel_a": "ch00",
            "constant": 1,
        }, progress_callback=callback)

        assert callback.call_count == 2

    def test_unknown_mode_raises(self, calculator_experiment):
        store, fov_id = calculator_experiment
        plugin = ImageCalculatorPlugin()
        with pytest.raises(RuntimeError, match="Unknown mode"):
            plugin.run(store, parameters={
                "mode": "invalid",
                "operation": "add",
                "fov_id": fov_id,
                "channel_a": "ch00",
                "constant": 1,
            })

    def test_no_parameters_raises(self, calculator_experiment):
        store, _fov_id = calculator_experiment
        plugin = ImageCalculatorPlugin()
        with pytest.raises(RuntimeError, match="Parameters are required"):
            plugin.run(store)
