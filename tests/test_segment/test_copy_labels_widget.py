"""Tests for copy_labels_to_fov() core logic."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from percell3.core import ExperimentStore
from percell3.segment.viewer.copy_labels_widget import copy_labels_to_fov


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_experiment_with_labels(tmp_path: Path) -> tuple[ExperimentStore, int]:
    """Create an experiment with one FOV that has labels and cells.

    Returns:
        (store, source_fov_id)
    """
    store = ExperimentStore.create(tmp_path / "copy_test.percell")
    store.add_channel("DAPI", role="segmentation")
    store.add_channel("GFP")
    store.add_condition("control")

    fov_id = store.add_fov("control", width=40, height=40, pixel_size_um=0.65)

    # Write images
    dapi = np.full((40, 40), 100, dtype=np.uint16)
    store.write_image(fov_id, "DAPI", dapi)

    # Write labels: 2 cells
    labels = np.zeros((40, 40), dtype=np.int32)
    labels[5:15, 5:15] = 1   # Cell 1
    labels[25:35, 25:35] = 2  # Cell 2

    from percell3.segment.roi_import import store_labels_and_cells

    seg_run_id = store.add_segmentation_run(
        fov_id=fov_id, channel="DAPI", model_name="mock",
        parameters={"diameter": 30.0},
    )
    store_labels_and_cells(store, labels, store.get_fov_by_id(fov_id), seg_run_id)

    return store, fov_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCopyLabelsToFov:
    """Tests for the core copy_labels_to_fov function."""

    def test_happy_path_copy(self, tmp_path: Path) -> None:
        """Copy labels from a source FOV to an empty target FOV."""
        store, source_fov_id = _create_experiment_with_labels(tmp_path)

        # Create empty target FOV with same dimensions
        target_fov_id = store.add_fov(
            "control", width=40, height=40, pixel_size_um=0.65,
            display_name="target_fov",
        )
        dapi = np.full((40, 40), 50, dtype=np.uint16)
        store.write_image(target_fov_id, "DAPI", dapi)

        run_id, cell_count = copy_labels_to_fov(
            store, source_fov_id, target_fov_id, "DAPI",
        )

        assert run_id > 0
        assert cell_count == 2

    def test_cell_count_matches_source(self, tmp_path: Path) -> None:
        """Target FOV should have the same number of cells as source."""
        store, source_fov_id = _create_experiment_with_labels(tmp_path)

        target_fov_id = store.add_fov(
            "control", width=40, height=40, pixel_size_um=0.65,
            display_name="target_fov",
        )

        _, cell_count = copy_labels_to_fov(
            store, source_fov_id, target_fov_id, "DAPI",
        )

        # Verify labels were actually written
        # Resolve run IDs for reading labels
        src_seg = store.list_segmentation_runs(source_fov_id)
        tgt_seg = store.list_segmentation_runs(target_fov_id)
        target_labels = store.read_labels(target_fov_id, tgt_seg[-1].id)
        source_labels = store.read_labels(source_fov_id, src_seg[-1].id)
        np.testing.assert_array_equal(target_labels, source_labels)
        assert cell_count == 2

    def test_error_on_no_source_labels(self, tmp_path: Path) -> None:
        """Raise KeyError if source FOV has no labels."""
        store = ExperimentStore.create(tmp_path / "no_labels.percell")
        store.add_channel("DAPI", role="segmentation")
        store.add_condition("control")

        source_fov_id = store.add_fov("control", width=40, height=40)
        target_fov_id = store.add_fov(
            "control", width=40, height=40, display_name="target",
        )

        with pytest.raises(KeyError):
            copy_labels_to_fov(store, source_fov_id, target_fov_id, "DAPI")

    def test_error_on_dimension_mismatch(self, tmp_path: Path) -> None:
        """Raise ValueError if source labels don't match target dimensions."""
        store, source_fov_id = _create_experiment_with_labels(tmp_path)

        # Create target with different dimensions
        target_fov_id = store.add_fov(
            "control", width=80, height=80, pixel_size_um=0.65,
            display_name="big_target",
        )

        with pytest.raises(ValueError, match="Dimension mismatch"):
            copy_labels_to_fov(store, source_fov_id, target_fov_id, "DAPI")

    def test_overwrite_existing_labels(self, tmp_path: Path) -> None:
        """Copying to a target that already has labels overwrites them."""
        store, source_fov_id = _create_experiment_with_labels(tmp_path)

        # Create target with its own labels (1 cell)
        target_fov_id = store.add_fov(
            "control", width=40, height=40, pixel_size_um=0.65,
            display_name="target_fov",
        )
        old_labels = np.zeros((40, 40), dtype=np.int32)
        old_labels[0:10, 0:10] = 1  # 1 cell

        from percell3.segment.roi_import import store_labels_and_cells

        old_run_id = store.add_segmentation_run(
            fov_id=target_fov_id, channel="DAPI", model_name="mock",
            parameters={},
        )
        store_labels_and_cells(
            store, old_labels, store.get_fov_by_id(target_fov_id), old_run_id,
        )

        # Now copy source labels (2 cells) to target
        _, cell_count = copy_labels_to_fov(
            store, source_fov_id, target_fov_id, "DAPI",
        )

        assert cell_count == 2
        # Labels should now match source
        tgt_seg = store.list_segmentation_runs(target_fov_id)
        src_seg = store.list_segmentation_runs(source_fov_id)
        target_labels = store.read_labels(target_fov_id, tgt_seg[-1].id)
        source_labels = store.read_labels(source_fov_id, src_seg[-1].id)
        np.testing.assert_array_equal(target_labels, source_labels)

    def test_segmentation_run_provenance(self, tmp_path: Path) -> None:
        """New segmentation run records label_copy method and source FOV ID."""
        store, source_fov_id = _create_experiment_with_labels(tmp_path)

        target_fov_id = store.add_fov(
            "control", width=40, height=40, pixel_size_um=0.65,
            display_name="target_fov",
        )

        run_id, _ = copy_labels_to_fov(
            store, source_fov_id, target_fov_id, "DAPI",
        )

        # Find the run we just created
        runs = store.list_segmentation_runs(target_fov_id)
        new_run = next(r for r in runs if r.id == run_id)
        assert new_run.model_name == "label_copy"
