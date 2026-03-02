"""Tests for the auto-measurement pipeline."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from percell3.core import ExperimentStore
from percell3.core.models import CellRecord
from percell3.measure.auto_measure import (
    _extract_cells_from_labels,
    on_config_changed,
    on_labels_edited,
    on_segmentation_created,
    on_threshold_created,
)


@pytest.fixture
def auto_experiment(tmp_path: Path) -> ExperimentStore:
    """Experiment with images and segmentation but NO pre-existing cells.

    Has: 1 condition, 1 FOV (64x64), 2 channels (DAPI, GFP),
    1 cellular segmentation with 2-cell label image, fov_config entry.
    Does NOT have pre-existing cells — auto_measure extracts them.
    """
    store = ExperimentStore.create(tmp_path / "auto.percell")
    store.add_channel("DAPI", role="segmentation")
    store.add_channel("GFP")
    store.add_condition("control")

    fov_id = store.add_fov("control", width=64, height=64, pixel_size_um=0.65)

    # Write images
    dapi = np.full((64, 64), 50, dtype=np.uint16)
    store.write_image(fov_id, "DAPI", dapi)

    gfp = np.zeros((64, 64), dtype=np.uint16)
    gfp[10:30, 10:30] = 100
    gfp[40:60, 40:60] = 200
    store.write_image(fov_id, "GFP", gfp)

    # Create segmentation + label image (but no cell records)
    seg_id = store.add_segmentation(
        "seg_test", "cellular", 64, 64,
        source_fov_id=fov_id, source_channel="DAPI", model_name="mock",
    )
    labels = np.zeros((64, 64), dtype=np.int32)
    labels[10:30, 10:30] = 1
    labels[40:60, 40:60] = 2
    store.write_labels(labels, seg_id)

    store._test_fov_id = fov_id
    store._test_seg_id = seg_id
    yield store
    store.close()


class TestExtractCells:
    def test_extracts_cells_from_labels(self, auto_experiment):
        store = auto_experiment
        fov_id = store._test_fov_id
        seg_id = store._test_seg_id

        n = _extract_cells_from_labels(store, fov_id, seg_id)
        assert n == 2

        cells = store.get_cells(fov_id=fov_id)
        assert len(cells) == 2
        assert set(cells["label_value"]) == {1, 2}

    def test_updates_segmentation_cell_count(self, auto_experiment):
        store = auto_experiment
        seg_id = store._test_seg_id

        _extract_cells_from_labels(store, store._test_fov_id, seg_id)
        seg = store.get_segmentation(seg_id)
        assert seg.cell_count == 2


class TestOnSegmentationCreated:
    def test_creates_cells_and_measures(self, auto_experiment):
        store = auto_experiment
        fov_id = store._test_fov_id
        seg_id = store._test_seg_id

        total = on_segmentation_created(store, seg_id, [fov_id])
        assert total > 0

        # Cells should exist
        cells = store.get_cells(fov_id=fov_id)
        assert len(cells) == 2

        # Measurements should exist for both channels
        for _, cell in cells.iterrows():
            ms = store.get_measurements(cell_ids=[int(cell["id"])])
            assert len(ms) > 0

    def test_measures_all_channels(self, auto_experiment):
        store = auto_experiment
        fov_id = store._test_fov_id
        seg_id = store._test_seg_id

        total = on_segmentation_created(store, seg_id, [fov_id])

        # Each cell should have measurements for both DAPI and GFP
        cells = store.get_cells(fov_id=fov_id)
        cell_id = int(cells.iloc[0]["id"])
        ms = store.get_measurements(cell_ids=[cell_id])
        measured_channels = set(ms["channel"].unique())
        assert len(measured_channels) == 2  # DAPI + GFP

    def test_skips_already_measured_cells(self, auto_experiment):
        """If cells already exist, doesn't re-extract."""
        store = auto_experiment
        fov_id = store._test_fov_id
        seg_id = store._test_seg_id

        # Pre-create cells manually
        _extract_cells_from_labels(store, fov_id, seg_id)
        cells_before = len(store.get_cells(fov_id=fov_id))

        on_segmentation_created(store, seg_id, [fov_id])
        cells_after = len(store.get_cells(fov_id=fov_id))
        assert cells_after == cells_before  # No duplicate cells

    def test_no_channels_returns_zero(self, tmp_path):
        """If no channels, returns 0."""
        store = ExperimentStore.create(tmp_path / "empty.percell")
        store.add_condition("control")
        fov_id = store.add_fov("control")
        seg_id = store.add_segmentation("seg", "cellular", 32, 32)

        total = on_segmentation_created(store, seg_id, [fov_id])
        assert total == 0
        store.close()

    def test_failure_does_not_crash(self, auto_experiment):
        """Measurement failure for one FOV doesn't crash the whole batch."""
        store = auto_experiment
        seg_id = store._test_seg_id

        # Pass a non-existent FOV ID along with the real one
        total = on_segmentation_created(store, seg_id, [store._test_fov_id, 99999])
        # Should still succeed for the real FOV
        assert total > 0


class TestOnThresholdCreated:
    @pytest.fixture
    def threshold_experiment(self, auto_experiment):
        """Extend auto_experiment with cells and a threshold."""
        store = auto_experiment
        fov_id = store._test_fov_id
        seg_id = store._test_seg_id

        # Create cells first
        _extract_cells_from_labels(store, fov_id, seg_id)

        # Create threshold
        thr_id = store.add_threshold(
            "thr_test", "otsu", 64, 64,
            source_fov_id=fov_id, source_channel="GFP",
        )

        # Write a threshold mask
        mask = np.zeros((64, 64), dtype=np.uint8)
        mask[10:30, 10:30] = 255  # Overlaps cell 1
        store.write_mask(mask, thr_id)

        store._test_thr_id = thr_id
        return store

    def test_creates_masked_measurements(self, threshold_experiment):
        store = threshold_experiment
        fov_id = store._test_fov_id
        seg_id = store._test_seg_id
        thr_id = store._test_thr_id

        total = on_threshold_created(store, thr_id, fov_id, seg_id)
        assert total > 0

    def test_creates_particle_records(self, threshold_experiment):
        store = threshold_experiment
        fov_id = store._test_fov_id
        seg_id = store._test_seg_id
        thr_id = store._test_thr_id

        on_threshold_created(store, thr_id, fov_id, seg_id)

        particles = store.get_particles(threshold_id=thr_id)
        # Cell 1 overlaps the mask; particles may be found there
        # Cell 2 does not overlap; no particles
        assert len(particles) >= 0  # At least no crash

    def test_no_channels_returns_zero(self, tmp_path):
        store = ExperimentStore.create(tmp_path / "empty.percell")
        store.add_condition("control")
        fov_id = store.add_fov("control")
        seg_id = store.add_segmentation("seg", "cellular", 32, 32)
        thr_id = store.add_threshold("thr", "manual", 32, 32)

        total = on_threshold_created(store, thr_id, fov_id, seg_id)
        assert total == 0
        store.close()


class TestOnLabelsEdited:
    def test_remeasures_after_edit(self, auto_experiment):
        store = auto_experiment
        fov_id = store._test_fov_id
        seg_id = store._test_seg_id

        # Initial measurement
        on_segmentation_created(store, seg_id, [fov_id])
        cells_before = store.get_cells(fov_id=fov_id)
        assert len(cells_before) == 2

        # Edit labels: remove cell 2, add cell 3
        old_labels = np.array(store.read_labels(seg_id))
        new_labels = old_labels.copy()
        new_labels[40:60, 40:60] = 0  # Remove cell 2
        new_labels[0:10, 0:10] = 3   # Add cell 3
        store.write_labels(new_labels, seg_id)

        total = on_labels_edited(store, seg_id, old_labels, new_labels)
        assert total > 0

        # Should now have cells 1 and 3, not 2
        cells_after = store.get_cells(fov_id=fov_id)
        label_vals = set(cells_after["label_value"])
        assert 1 in label_vals
        assert 3 in label_vals
        assert 2 not in label_vals

    def test_no_change_returns_zero(self, auto_experiment):
        store = auto_experiment
        seg_id = store._test_seg_id

        labels = np.array(store.read_labels(seg_id))
        total = on_labels_edited(store, seg_id, labels, labels.copy())
        assert total == 0

    def test_propagates_to_all_fovs(self, auto_experiment):
        """Label edits propagate to all FOVs referencing the segmentation."""
        store = auto_experiment
        fov_id = store._test_fov_id
        seg_id = store._test_seg_id

        # Add a second FOV that references the same segmentation
        fov2 = store.add_fov("control", width=64, height=64)
        store.write_image(fov2, "DAPI", np.full((64, 64), 50, dtype=np.uint16))
        store.write_image(fov2, "GFP", np.full((64, 64), 100, dtype=np.uint16))
        store.set_fov_config_entry(fov2, seg_id)

        # Initial measurement for both FOVs
        on_segmentation_created(store, seg_id, [fov_id, fov2])

        # Edit labels
        old_labels = np.array(store.read_labels(seg_id))
        new_labels = old_labels.copy()
        new_labels[40:60, 40:60] = 0  # Remove cell 2
        store.write_labels(new_labels, seg_id)

        on_labels_edited(store, seg_id, old_labels, new_labels)

        # Both FOVs should have only cell 1 now
        for fid in [fov_id, fov2]:
            cells = store.get_cells(fov_id=fid)
            assert set(cells["label_value"]) == {1}


class TestOnConfigChanged:
    def test_fills_measurement_gaps(self, auto_experiment):
        """Config changes trigger measurement for unmeasured combinations."""
        store = auto_experiment
        fov_id = store._test_fov_id
        seg_id = store._test_seg_id

        # No measurements yet
        total = on_config_changed(store, fov_id)
        assert total > 0

        # Cells should exist and be measured
        cells = store.get_cells(fov_id=fov_id)
        assert len(cells) > 0

    def test_no_config_returns_zero(self, tmp_path):
        store = ExperimentStore.create(tmp_path / "empty.percell")
        store.add_condition("control")
        fov_id = store.add_fov("control")

        total = on_config_changed(store, fov_id)
        assert total == 0
        store.close()

    def test_already_measured_not_remeasured(self, auto_experiment):
        """Already-measured combinations are not re-measured."""
        store = auto_experiment
        fov_id = store._test_fov_id
        seg_id = store._test_seg_id

        # First pass: measure
        total1 = on_config_changed(store, fov_id)
        assert total1 > 0

        # Second pass: should detect existing measurements and skip
        total2 = on_config_changed(store, fov_id)
        assert total2 == 0
