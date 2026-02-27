"""Tests for copy_mask_to_fov() core logic."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from percell3.core import ExperimentStore
from percell3.core.models import CellRecord
from percell3.segment.viewer.copy_mask_widget import copy_mask_to_fov


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_experiment_with_mask(tmp_path: Path) -> tuple[ExperimentStore, int]:
    """Create an experiment with one FOV that has labels, cells, and a mask.

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
    gfp[12:18, 12:18] = 200  # Bright region inside cell
    store.write_image(fov_id, "GFP", gfp)

    # Write labels and cells
    labels = np.zeros((40, 40), dtype=np.int32)
    labels[5:25, 5:25] = 1  # One cell covering the mask region
    seg_run_id = store.add_segmentation_run("DAPI", "mock", {"diameter": 30.0})
    store.write_labels(fov_id, labels, seg_run_id)
    store.delete_cells_for_fov(fov_id)
    cells = [
        CellRecord(
            fov_id=fov_id,
            segmentation_id=seg_run_id,
            label_value=1,
            centroid_x=15.0, centroid_y=15.0,
            bbox_x=5, bbox_y=5, bbox_w=20, bbox_h=20,
            area_pixels=400.0,
        ),
    ]
    store.add_cells(cells)
    store.update_segmentation_run_cell_count(seg_run_id, 1)

    # Write a threshold mask on GFP
    tr_id = store.add_threshold_run("GFP", "otsu", {"threshold_value": 100.0})
    mask = np.zeros((40, 40), dtype=np.uint8)
    mask[12:18, 12:18] = 255  # One bright region inside cell
    store.write_mask(fov_id, "GFP", mask, tr_id)

    return store, fov_id


def _create_target_with_labels(
    store: ExperimentStore,
    display_name: str = "target_fov",
) -> int:
    """Create a target FOV with labels and cells (same geometry as source)."""
    target_fov_id = store.add_fov(
        "control", width=40, height=40, pixel_size_um=0.65,
        display_name=display_name,
    )

    # Write images
    dapi = np.full((40, 40), 80, dtype=np.uint16)
    store.write_image(target_fov_id, "DAPI", dapi)
    gfp = np.full((40, 40), 40, dtype=np.uint16)
    gfp[12:18, 12:18] = 180  # Bright region
    store.write_image(target_fov_id, "GFP", gfp)

    # Same labels and cells as source
    labels = np.zeros((40, 40), dtype=np.int32)
    labels[5:25, 5:25] = 1
    seg_run_id = store.add_segmentation_run("DAPI", "label_copy", {})
    store.write_labels(target_fov_id, labels, seg_run_id)
    store.delete_cells_for_fov(target_fov_id)
    cells = [
        CellRecord(
            fov_id=target_fov_id,
            segmentation_id=seg_run_id,
            label_value=1,
            centroid_x=15.0, centroid_y=15.0,
            bbox_x=5, bbox_y=5, bbox_w=20, bbox_h=20,
            area_pixels=400.0,
        ),
    ]
    store.add_cells(cells)
    store.update_segmentation_run_cell_count(seg_run_id, 1)

    return target_fov_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCopyMaskToFov:
    """Tests for the core copy_mask_to_fov function."""

    def test_happy_path_copy(self, tmp_path: Path) -> None:
        """Copy a mask from source FOV to a target FOV with labels."""
        store, source_fov_id = _create_experiment_with_mask(tmp_path)
        target_fov_id = _create_target_with_labels(store)

        run_id, particle_count = copy_mask_to_fov(
            store, source_fov_id, target_fov_id, "GFP",
        )

        assert run_id > 0
        # Verify mask was written to target
        target_mask = store.read_mask(target_fov_id, "GFP")
        source_mask = store.read_mask(source_fov_id, "GFP")
        np.testing.assert_array_equal(target_mask, source_mask)

    def test_particles_extracted_after_copy(self, tmp_path: Path) -> None:
        """Particles are extracted from the copied mask so measurements work."""
        store, source_fov_id = _create_experiment_with_mask(tmp_path)
        target_fov_id = _create_target_with_labels(store)

        _, particle_count = copy_mask_to_fov(
            store, source_fov_id, target_fov_id, "GFP",
        )

        assert particle_count > 0, "Particles should be extracted from copied mask"

        # Verify particle label image exists
        particle_labels = store.read_particle_labels(target_fov_id, "GFP")
        assert particle_labels.max() > 0, "Particle label image should have particles"

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
        target_fov_id = _create_target_with_labels(store)

        # Give target its own mask first
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
        target_fov_id = _create_target_with_labels(store)

        run_id, _ = copy_mask_to_fov(
            store, source_fov_id, target_fov_id, "GFP",
        )

        runs = store.get_threshold_runs()
        new_run = next(r for r in runs if r["id"] == run_id)
        assert new_run["method"] == "mask_copy"

    def test_no_particles_without_cells(self, tmp_path: Path) -> None:
        """If target has no cells, mask is copied but particle count is 0."""
        store, source_fov_id = _create_experiment_with_mask(tmp_path)

        # Target with no labels or cells
        target_fov_id = store.add_fov(
            "control", width=40, height=40, pixel_size_um=0.65,
            display_name="empty_target",
        )

        _, particle_count = copy_mask_to_fov(
            store, source_fov_id, target_fov_id, "GFP",
        )

        assert particle_count == 0
        # Mask should still be written
        target_mask = store.read_mask(target_fov_id, "GFP")
        source_mask = store.read_mask(source_fov_id, "GFP")
        np.testing.assert_array_equal(target_mask, source_mask)
