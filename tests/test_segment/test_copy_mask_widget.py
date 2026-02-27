"""Tests for copy_mask_to_fov() core logic."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from percell3.core import ExperimentStore
from percell3.segment.viewer.copy_mask_widget import copy_mask_to_fov


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_experiment_with_mask(tmp_path: Path) -> tuple[ExperimentStore, int]:
    """Create an experiment with one FOV that has a threshold mask.

    Returns:
        (store, source_fov_id)
    """
    store = ExperimentStore.create(tmp_path / "mask_test.percell")
    store.add_channel("DAPI", role="segmentation")
    store.add_channel("GFP")
    store.add_condition("control")

    fov_id = store.add_fov("control", width=40, height=40, pixel_size_um=0.65)

    # Write images
    dapi = np.full((40, 40), 100, dtype=np.uint16)
    store.write_image(fov_id, "DAPI", dapi)
    gfp = np.full((40, 40), 50, dtype=np.uint16)
    store.write_image(fov_id, "GFP", gfp)

    # Write a threshold mask on GFP
    tr_id = store.add_threshold_run("GFP", "otsu", {"threshold_value": 100.0})
    mask = np.zeros((40, 40), dtype=np.uint8)
    mask[10:20, 10:20] = 255  # One bright region
    store.write_mask(fov_id, "GFP", mask, tr_id)

    return store, fov_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCopyMaskToFov:
    """Tests for the core copy_mask_to_fov function."""

    def test_happy_path_copy(self, tmp_path: Path) -> None:
        """Copy a mask from source FOV to an empty target FOV."""
        store, source_fov_id = _create_experiment_with_mask(tmp_path)

        target_fov_id = store.add_fov(
            "control", width=40, height=40, pixel_size_um=0.65,
            display_name="target_fov",
        )

        run_id = copy_mask_to_fov(store, source_fov_id, target_fov_id, "GFP")

        assert run_id > 0
        # Verify mask was written to target
        target_mask = store.read_mask(target_fov_id, "GFP")
        source_mask = store.read_mask(source_fov_id, "GFP")
        np.testing.assert_array_equal(target_mask, source_mask)

    def test_error_on_no_source_mask(self, tmp_path: Path) -> None:
        """Raise KeyError if source FOV has no mask for the channel."""
        store = ExperimentStore.create(tmp_path / "no_mask.percell")
        store.add_channel("GFP")
        store.add_condition("control")

        source_fov_id = store.add_fov("control", width=40, height=40)
        target_fov_id = store.add_fov(
            "control", width=40, height=40, display_name="target",
        )

        with pytest.raises(KeyError):
            copy_mask_to_fov(store, source_fov_id, target_fov_id, "GFP")

    def test_error_on_dimension_mismatch(self, tmp_path: Path) -> None:
        """Raise ValueError if source mask doesn't match target dimensions."""
        store, source_fov_id = _create_experiment_with_mask(tmp_path)

        target_fov_id = store.add_fov(
            "control", width=80, height=80, pixel_size_um=0.65,
            display_name="big_target",
        )

        with pytest.raises(ValueError, match="Dimension mismatch"):
            copy_mask_to_fov(store, source_fov_id, target_fov_id, "GFP")

    def test_overwrite_existing_mask(self, tmp_path: Path) -> None:
        """Copying to a target that already has a mask overwrites it."""
        store, source_fov_id = _create_experiment_with_mask(tmp_path)

        # Create target with its own mask
        target_fov_id = store.add_fov(
            "control", width=40, height=40, pixel_size_um=0.65,
            display_name="target_fov",
        )
        old_tr_id = store.add_threshold_run("GFP", "manual", {})
        old_mask = np.ones((40, 40), dtype=np.uint8) * 128
        store.write_mask(target_fov_id, "GFP", old_mask, old_tr_id)

        # Copy source mask to target
        copy_mask_to_fov(store, source_fov_id, target_fov_id, "GFP")

        # Target should now have source's mask
        target_mask = store.read_mask(target_fov_id, "GFP")
        source_mask = store.read_mask(source_fov_id, "GFP")
        np.testing.assert_array_equal(target_mask, source_mask)

    def test_threshold_run_provenance(self, tmp_path: Path) -> None:
        """New threshold run records mask_copy method and source FOV ID."""
        store, source_fov_id = _create_experiment_with_mask(tmp_path)

        target_fov_id = store.add_fov(
            "control", width=40, height=40, pixel_size_um=0.65,
            display_name="target_fov",
        )

        run_id = copy_mask_to_fov(store, source_fov_id, target_fov_id, "GFP")

        runs = store.get_threshold_runs()
        new_run = next(r for r in runs if r["id"] == run_id)
        assert new_run["method"] == "mask_copy"
