"""Reproduce the auto-measure → grouper bug from the threshold flow."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from percell3.core import ExperimentStore
from percell3.measure.cell_grouper import CellGrouper
from percell3.measure.measurer import Measurer
from percell3.segment.label_processor import extract_cells


def _create_experiment_with_two_channels(tmp_path: Path) -> ExperimentStore:
    """Create experiment with ch00 (seg) and ch01 (measurement)."""
    store = ExperimentStore.create(tmp_path / "test.percell")
    store.add_channel("ch00", role="segmentation")
    store.add_channel("ch01")
    store.add_condition("control")
    return store


def _add_fov_single_cell(
    store: ExperimentStore, width: int = 100, height: int = 100,
) -> tuple[int, int]:
    """Add FOV with 1 large cell. Returns (fov_id, seg_id)."""
    fov_id = store.add_fov(
        "control", width=width, height=height,
        pixel_size_um=0.65, display_name="fov1",
    )
    # Write channel images
    ch00_img = np.full((height, width), 50, dtype=np.uint16)
    ch01_img = np.full((height, width), 200, dtype=np.uint16)
    store.write_image(fov_id, "ch00", ch00_img)
    store.write_image(fov_id, "ch01", ch01_img)

    # Create labels with 1 cell
    labels = np.zeros((height, width), dtype=np.int32)
    labels[10:60, 10:60] = 1  # 50x50 cell

    seg_id = store.add_segmentation(
        "seg_test", "cellular", width, height,
        source_fov_id=fov_id, source_channel="ch00", model_name="napari_edit",
        parameters={},
    )
    store.write_labels(labels, seg_id)

    cells = extract_cells(labels, fov_id, seg_id, 0.65)
    assert len(cells) == 1, f"Expected 1 cell, got {len(cells)}"
    store.add_cells(cells)
    store.update_segmentation_cell_count(seg_id, len(cells))

    return fov_id, seg_id


class TestAutoMeasureThenGrouper:
    """Reproduce: auto-measure completes but grouper can't find measurements."""

    def test_measure_fov_creates_measurements(self, tmp_path):
        """measure_fov with seg_id should write measurements."""
        store = _create_experiment_with_two_channels(tmp_path)
        fov_id, seg_id = _add_fov_single_cell(store)

        measurer = Measurer()
        count = measurer.measure_fov(
            store, fov_id=fov_id, channels=["ch00", "ch01"],
            segmentation_id=seg_id,
        )
        assert count > 0, "measure_fov returned 0 — no measurements written!"

        # Verify measurements in DB
        measured = store.list_measured_channels()
        assert "ch01" in measured, f"ch01 not in measured channels: {measured}"

    def test_grouper_finds_measurements_after_auto_measure(self, tmp_path):
        """After measure_fov, group_cells should find integrated_intensity."""
        store = _create_experiment_with_two_channels(tmp_path)
        fov_id, seg_id = _add_fov_single_cell(store)

        # Auto-measure (same as threshold flow)
        measurer = Measurer()
        count = measurer.measure_fov(
            store, fov_id=fov_id, channels=["ch00", "ch01"],
            segmentation_id=seg_id,
        )
        assert count > 0

        # Now group cells — this is what fails in the user's report
        grouper = CellGrouper()
        result = grouper.group_cells(
            store, fov_id=fov_id,
            channel="ch01", metric="integrated_intensity",
        )
        assert result.n_groups >= 1
        assert len(result.cell_ids) == 1

    def test_measure_fov_with_explicit_seg_id(self, tmp_path):
        """measure_fov with explicit segmentation_id should work."""
        store = _create_experiment_with_two_channels(tmp_path)
        fov_id, seg_id = _add_fov_single_cell(store)

        measurer = Measurer()
        count = measurer.measure_fov(
            store, fov_id=fov_id, channels=["ch00", "ch01"],
            segmentation_id=seg_id,
        )
        assert count > 0

    def test_cells_have_correct_segmentation_id(self, tmp_path):
        """Verify cells DataFrame has segmentation_id matching the segmentation."""
        store = _create_experiment_with_two_channels(tmp_path)
        fov_id, seg_id = _add_fov_single_cell(store)

        cells_df = store.get_cells(fov_id=fov_id)
        assert not cells_df.empty, "No cells returned by get_cells"
        assert "segmentation_id" in cells_df.columns
        assert cells_df.iloc[0]["segmentation_id"] == seg_id

    def test_labels_readable(self, tmp_path):
        """Verify labels can be read from seg_{id}/0 path."""
        store = _create_experiment_with_two_channels(tmp_path)
        fov_id, seg_id = _add_fov_single_cell(store)

        labels = store.read_labels(seg_id)
        assert labels.shape == (100, 100)
        assert labels.max() == 1  # 1 cell

    def test_full_threshold_flow_simulation(self, tmp_path):
        """Simulate the exact sequence from _apply_threshold."""
        store = _create_experiment_with_two_channels(tmp_path)
        fov_id, seg_id = _add_fov_single_cell(store)

        ch_names = [ch.name for ch in store.get_channels()]

        # Step 1: Check for existing measurements
        measured = store.list_measured_channels()
        assert len(measured) == 0, "Should start with no measurements"

        # Step 2: Auto-measure
        measurer = Measurer()
        count = measurer.measure_fov(
            store, fov_id=fov_id, channels=ch_names, segmentation_id=seg_id,
        )
        assert count > 0, f"Auto-measure produced {count} measurements"

        # Step 3: Verify measurements visible
        measured_after = store.list_measured_channels()
        assert len(measured_after) > 0, "Measurements not visible after measure_fov"

        # Step 4: Group cells
        grouper = CellGrouper()
        result = grouper.group_cells(
            store, fov_id=fov_id,
            channel="ch01", metric="integrated_intensity",
        )
        assert result.n_groups >= 1
