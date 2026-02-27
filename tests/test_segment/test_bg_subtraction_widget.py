"""Tests for subtract_background_to_derived_fov() core logic."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from percell3.core import ExperimentStore
from percell3.segment.viewer.bg_subtraction_widget import (
    subtract_background_to_derived_fov,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_bg_experiment(tmp_path: Path) -> tuple[ExperimentStore, int]:
    """Create a minimal experiment with two channels for BG subtraction tests.

    Returns:
        (store, fov_id)
    """
    store = ExperimentStore.create(tmp_path / "bg_test.percell")
    store.add_channel("DAPI", role="segmentation")
    store.add_channel("GFP")
    store.add_condition("control")

    fov_id = store.add_fov("control", width=20, height=20, pixel_size_um=0.65)

    # DAPI: uniform 100
    dapi = np.full((20, 20), 100, dtype=np.uint16)
    store.write_image(fov_id, "DAPI", dapi)

    # GFP: gradient 0–399 reshaped to 20x20
    gfp = np.arange(400, dtype=np.uint16).reshape(20, 20)
    store.write_image(fov_id, "GFP", gfp)

    return store, fov_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSubtractBackgroundToDerivedFov:
    """Tests for the core subtract_background_to_derived_fov function."""

    def test_subtraction_clips_to_zero(self, tmp_path: Path) -> None:
        """Subtracted values below zero are clipped to 0."""
        store, fov_id = _create_bg_experiment(tmp_path)

        derived_fov_id, n = subtract_background_to_derived_fov(
            store, fov_id, bg_value=200.0, selected_channels=["GFP"],
        )

        result = store.read_image_numpy(derived_fov_id, "GFP")
        assert result.min() >= 0, "Subtraction produced negative values"
        # Pixels with original value < 200 should be clipped to 0
        assert result[0, 0] == 0  # original was 0
        assert result[0, 50 // 20] == 0  # original < 200

    def test_dtype_preservation_uint16(self, tmp_path: Path) -> None:
        """Output image preserves the original uint16 dtype."""
        store, fov_id = _create_bg_experiment(tmp_path)

        derived_fov_id, _ = subtract_background_to_derived_fov(
            store, fov_id, bg_value=10.0, selected_channels=["GFP"],
        )

        result = store.read_image_numpy(derived_fov_id, "GFP")
        assert result.dtype == np.uint16

    def test_dtype_preservation_uint8(self, tmp_path: Path) -> None:
        """Output image preserves uint8 dtype."""
        store = ExperimentStore.create(tmp_path / "u8_test.percell")
        store.add_channel("CH1")
        store.add_condition("ctrl")
        fov_id = store.add_fov("ctrl", width=10, height=10, pixel_size_um=0.5)

        img = np.full((10, 10), 200, dtype=np.uint8)
        store.write_image(fov_id, "CH1", img)

        derived_fov_id, _ = subtract_background_to_derived_fov(
            store, fov_id, bg_value=50.0, selected_channels=["CH1"],
        )

        result = store.read_image_numpy(derived_fov_id, "CH1")
        assert result.dtype == np.uint8
        np.testing.assert_array_equal(result, 150)

    def test_derived_fov_created_with_correct_name(self, tmp_path: Path) -> None:
        """Derived FOV is named bg_sub_{original_display_name}."""
        store, fov_id = _create_bg_experiment(tmp_path)

        derived_fov_id, _ = subtract_background_to_derived_fov(
            store, fov_id, bg_value=10.0, selected_channels=["GFP"],
        )

        fovs = {f.display_name: f.id for f in store.get_fovs()}
        original_fov = store.get_fov_by_id(fov_id)
        expected_name = f"bg_sub_{original_fov.display_name}"

        assert expected_name in fovs
        assert fovs[expected_name] == derived_fov_id

    def test_rerun_overwrites_existing_derived_fov(self, tmp_path: Path) -> None:
        """Running subtraction twice reuses the same derived FOV ID."""
        store, fov_id = _create_bg_experiment(tmp_path)

        # First run with bg=10
        derived_id_1, _ = subtract_background_to_derived_fov(
            store, fov_id, bg_value=10.0, selected_channels=["GFP"],
        )

        # Second run with bg=50
        derived_id_2, _ = subtract_background_to_derived_fov(
            store, fov_id, bg_value=50.0, selected_channels=["GFP"],
        )

        assert derived_id_1 == derived_id_2, "Re-run should reuse same derived FOV"

        # Verify the data reflects the second subtraction (bg=50)
        result = store.read_image_numpy(derived_id_2, "GFP")
        # Original GFP[0,0] = 0, after bg=50 should be 0 (clipped)
        assert result[0, 0] == 0
        # Original GFP[19,19] = 399, after bg=50 should be 349
        assert result[19, 19] == 349

    def test_unselected_channels_copied_unchanged(self, tmp_path: Path) -> None:
        """Channels not in selected_channels are copied to derived FOV unchanged."""
        store, fov_id = _create_bg_experiment(tmp_path)

        # Only subtract from GFP, not DAPI
        derived_fov_id, n = subtract_background_to_derived_fov(
            store, fov_id, bg_value=50.0, selected_channels=["GFP"],
        )

        assert n == 2, "Both channels should be written"

        # DAPI should be unchanged (all 100)
        dapi_result = store.read_image_numpy(derived_fov_id, "DAPI")
        np.testing.assert_array_equal(dapi_result, 100)

        # GFP should be subtracted
        gfp_result = store.read_image_numpy(derived_fov_id, "GFP")
        original_gfp = store.read_image_numpy(fov_id, "GFP")
        expected = np.clip(original_gfp.astype(np.float64) - 50.0, 0, None).astype(
            np.uint16
        )
        np.testing.assert_array_equal(gfp_result, expected)

    def test_subtraction_math_correct(self, tmp_path: Path) -> None:
        """Verify the subtraction produces correct numeric results."""
        store, fov_id = _create_bg_experiment(tmp_path)

        derived_fov_id, _ = subtract_background_to_derived_fov(
            store, fov_id, bg_value=100.0, selected_channels=["GFP"],
        )

        result = store.read_image_numpy(derived_fov_id, "GFP")
        original = store.read_image_numpy(fov_id, "GFP")

        # Values >= 100 should be reduced by 100
        assert result[5, 5] == max(0, int(original[5, 5]) - 100)
        # Last pixel: 399 - 100 = 299
        assert result[19, 19] == 299
        # First pixel: 0 - 100 = clipped to 0
        assert result[0, 0] == 0

    def test_all_channels_selected(self, tmp_path: Path) -> None:
        """When all channels are selected, all are subtracted."""
        store, fov_id = _create_bg_experiment(tmp_path)

        derived_fov_id, n = subtract_background_to_derived_fov(
            store, fov_id, bg_value=30.0, selected_channels=["DAPI", "GFP"],
        )

        assert n == 2

        # DAPI: 100 - 30 = 70
        dapi_result = store.read_image_numpy(derived_fov_id, "DAPI")
        np.testing.assert_array_equal(dapi_result, 70)

        # GFP: subtracted by 30
        gfp_result = store.read_image_numpy(derived_fov_id, "GFP")
        assert gfp_result[0, 0] == 0  # 0 - 30 → 0
        assert gfp_result[19, 19] == 369  # 399 - 30
