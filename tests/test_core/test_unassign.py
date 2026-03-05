"""Tests for unassigning segmentations and thresholds from FOVs."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from percell3.core.experiment_store import ExperimentStore
from percell3.core.models import CellRecord, MeasurementRecord, ParticleRecord


@pytest.fixture
def store(tmp_path: Path) -> ExperimentStore:
    """A fresh experiment store."""
    s = ExperimentStore.create(tmp_path / "test.percell", name="Test")
    yield s
    s.close()


@pytest.fixture
def store_with_data(store: ExperimentStore) -> ExperimentStore:
    """Store with 2 FOVs, a shared cellular seg, threshold, cells, measurements, particles."""
    store.add_channel("DAPI", color="#0000FF")
    store.add_channel("GFP", color="#00FF00")
    store.add_condition("ctrl")

    fov1 = store.add_fov("ctrl", width=64, height=64)
    fov2 = store.add_fov("ctrl", width=64, height=64)

    seg = store.add_segmentation(
        "cellular_1", "cellular", 64, 64,
        source_fov_id=fov1, source_channel="DAPI",
    )

    # Write label images
    labels = np.ones((64, 64), dtype=np.int32)
    store.write_labels(labels, seg)

    # Add cells for both FOVs
    cells_fov1 = [
        CellRecord(
            fov_id=fov1, segmentation_id=seg, label_value=i,
            centroid_x=10.0, centroid_y=10.0,
            bbox_x=0, bbox_y=0, bbox_w=30, bbox_h=30,
            area_pixels=900.0,
        )
        for i in range(1, 4)
    ]
    cells_fov2 = [
        CellRecord(
            fov_id=fov2, segmentation_id=seg, label_value=i,
            centroid_x=10.0, centroid_y=10.0,
            bbox_x=0, bbox_y=0, bbox_w=30, bbox_h=30,
            area_pixels=900.0,
        )
        for i in range(1, 3)
    ]
    ids_fov1 = store.add_cells(cells_fov1)
    ids_fov2 = store.add_cells(cells_fov2)

    # Add threshold
    thr = store.add_threshold(
        "thr_1", "manual", 64, 64,
        source_channel="GFP",
    )
    mask = np.zeros((64, 64), dtype=np.uint8)
    mask[10:30, 10:30] = 255
    store.write_mask(mask, thr)

    # Config: assign seg+threshold to both FOVs
    store.set_fov_config_entry(fov1, seg, threshold_id=thr)
    store.set_fov_config_entry(fov2, seg, threshold_id=thr)

    # Measurements: non-threshold (seg-only) + threshold-scoped
    gfp = store.get_channel("GFP")
    non_thr_meas = [
        MeasurementRecord(
            cell_id=cid, channel_id=gfp.id,
            metric="mean_intensity", value=42.0,
            segmentation_id=seg,
        )
        for cid in ids_fov1 + ids_fov2
    ]
    thr_meas = [
        MeasurementRecord(
            cell_id=cid, channel_id=gfp.id,
            metric="particle_count", value=5.0,
            threshold_id=thr, segmentation_id=seg,
        )
        for cid in ids_fov1 + ids_fov2
    ]
    store.add_measurements(non_thr_meas + thr_meas)

    # Particles for both FOVs
    particles = [
        ParticleRecord(
            fov_id=fov_id, threshold_id=thr, label_value=1,
            centroid_x=15.0, centroid_y=15.0,
            bbox_x=10, bbox_y=10, bbox_w=5, bbox_h=5,
            area_pixels=25.0,
        )
        for fov_id in [fov1, fov2]
    ]
    store.add_particles(particles)

    # Stash IDs for tests
    store._test_fov1 = fov1
    store._test_fov2 = fov2
    store._test_seg = seg
    store._test_thr = thr
    store._test_ids_fov1 = ids_fov1
    store._test_ids_fov2 = ids_fov2
    return store


class TestUnassignThreshold:
    """Tests for unassign_threshold_from_fov()."""

    def test_removes_threshold_measurements(self, store_with_data):
        s = store_with_data
        fov1, thr = s._test_fov1, s._test_thr

        result = s.unassign_threshold_from_fov(thr, fov1)

        assert result["measurements_deleted"] == 3  # 3 cells in fov1
        assert result["particles_deleted"] == 1
        assert result["config_entries_deleted"] == 1

    def test_preserves_other_fov_data(self, store_with_data):
        s = store_with_data
        fov1, fov2, thr = s._test_fov1, s._test_fov2, s._test_thr

        s.unassign_threshold_from_fov(thr, fov1)

        # FOV2 should still have its threshold data
        config = s.get_fov_config(fov2)
        thr_entries = [e for e in config if e.threshold_id == thr]
        assert len(thr_entries) == 1

        # FOV2 measurements with threshold still exist
        all_meas = s.get_measurements()
        fov2_thr_meas = [
            m for m in all_meas.itertuples()
            if m.cell_id in s._test_ids_fov2
            and hasattr(m, "threshold_id") and m.threshold_id == thr
        ]
        # Check via raw query
        conn = s._conn
        count = conn.execute(
            "SELECT COUNT(*) FROM measurements WHERE threshold_id = ? "
            "AND cell_id IN (SELECT id FROM cells WHERE fov_id = ?)",
            (thr, fov2),
        ).fetchone()[0]
        assert count == 2  # 2 cells in fov2

    def test_preserves_non_threshold_measurements(self, store_with_data):
        s = store_with_data
        fov1, thr, seg = s._test_fov1, s._test_thr, s._test_seg

        s.unassign_threshold_from_fov(thr, fov1)

        # Non-threshold measurements for fov1 cells should still exist
        conn = s._conn
        count = conn.execute(
            "SELECT COUNT(*) FROM measurements WHERE threshold_id IS NULL "
            "AND cell_id IN (SELECT id FROM cells WHERE fov_id = ?)",
            (fov1,),
        ).fetchone()[0]
        assert count == 3  # 3 cells, each with mean_intensity

    def test_noop_when_not_assigned(self, store_with_data):
        s = store_with_data
        fov1, thr = s._test_fov1, s._test_thr

        # Unassign first time
        s.unassign_threshold_from_fov(thr, fov1)
        # Second time should be a no-op
        result = s.unassign_threshold_from_fov(thr, fov1)

        assert result["measurements_deleted"] == 0
        assert result["particles_deleted"] == 0
        assert result["config_entries_deleted"] == 0

    def test_config_entry_removed(self, store_with_data):
        s = store_with_data
        fov1, thr = s._test_fov1, s._test_thr

        s.unassign_threshold_from_fov(thr, fov1)

        config = s.get_fov_config(fov1)
        thr_entries = [e for e in config if e.threshold_id == thr]
        assert len(thr_entries) == 0


class TestUnassignSegmentation:
    """Tests for unassign_segmentation_from_fov()."""

    def test_removes_cells_and_measurements(self, store_with_data):
        s = store_with_data
        fov1, seg = s._test_fov1, s._test_seg

        result = s.unassign_segmentation_from_fov(seg, fov1)

        assert result["cells_deleted"] == 3
        # 3 cells x 2 measurements each (mean_intensity + particle_count)
        assert result["measurements_deleted"] == 6
        assert result["particles_deleted"] == 1
        # 2 config entries: _auto_config_segmentation creates (seg, thr=None)
        # and set_fov_config_entry creates (seg, thr=thr)
        assert result["config_entries_deleted"] == 2

    def test_preserves_other_fov_data(self, store_with_data):
        s = store_with_data
        fov1, fov2, seg = s._test_fov1, s._test_fov2, s._test_seg

        s.unassign_segmentation_from_fov(seg, fov1)

        # FOV2 cells still exist
        cells_fov2 = s.get_cells(fov_id=fov2)
        assert len(cells_fov2) == 2

        # FOV2 config entry still exists
        config = s.get_fov_config(fov2)
        seg_entries = [e for e in config if e.segmentation_id == seg]
        assert len(seg_entries) == 1

    def test_whole_field_guard(self, store_with_data):
        s = store_with_data
        fov1 = s._test_fov1

        # Get the whole_field segmentation (auto-created with FOV)
        config = s.get_fov_config(fov1)
        # Find a whole_field seg - there should be one from FOV creation
        segs = s.get_segmentations()
        wf_segs = [seg for seg in segs if seg.seg_type == "whole_field"]
        assert len(wf_segs) > 0

        with pytest.raises(ValueError, match="whole_field"):
            s.unassign_segmentation_from_fov(wf_segs[0].id, fov1)

    def test_noop_when_not_assigned(self, store_with_data):
        s = store_with_data
        fov1, seg = s._test_fov1, s._test_seg

        s.unassign_segmentation_from_fov(seg, fov1)
        result = s.unassign_segmentation_from_fov(seg, fov1)

        assert result["cells_deleted"] == 0
        assert result["measurements_deleted"] == 0
        assert result["config_entries_deleted"] == 0

    def test_config_entry_removed(self, store_with_data):
        s = store_with_data
        fov1, seg = s._test_fov1, s._test_seg

        s.unassign_segmentation_from_fov(seg, fov1)

        config = s.get_fov_config(fov1)
        seg_entries = [e for e in config if e.segmentation_id == seg]
        assert len(seg_entries) == 0


class TestUnassignQueries:
    """Tests for the query-level delete functions."""

    def test_delete_measurements_for_fov_threshold(self, store_with_data):
        from percell3.core import queries

        s = store_with_data
        fov1, thr = s._test_fov1, s._test_thr

        count = queries.delete_measurements_for_fov_threshold(s._conn, fov1, thr)
        assert count == 3  # 3 cells in fov1 with threshold measurements

        # Verify fov2 threshold measurements still exist
        remaining = s._conn.execute(
            "SELECT COUNT(*) FROM measurements WHERE threshold_id = ?",
            (thr,),
        ).fetchone()[0]
        assert remaining == 2  # fov2 has 2 cells

    def test_delete_measurements_for_fov_segmentation(self, store_with_data):
        from percell3.core import queries

        s = store_with_data
        fov1, seg = s._test_fov1, s._test_seg

        count = queries.delete_measurements_for_fov_segmentation(s._conn, fov1, seg)
        assert count == 6  # 3 cells x 2 metrics

        # Verify fov2 measurements still exist
        remaining = s._conn.execute(
            "SELECT COUNT(*) FROM measurements WHERE cell_id IN "
            "(SELECT id FROM cells WHERE fov_id = ?)",
            (s._test_fov2,),
        ).fetchone()[0]
        assert remaining == 4  # 2 cells x 2 metrics

    def test_delete_cells_for_fov_segmentation(self, store_with_data):
        from percell3.core import queries

        s = store_with_data
        fov1, seg = s._test_fov1, s._test_seg

        count = queries.delete_cells_for_fov_segmentation(s._conn, fov1, seg)
        assert count == 3

        # Verify fov2 cells still exist
        remaining = s._conn.execute(
            "SELECT COUNT(*) FROM cells WHERE fov_id = ?",
            (s._test_fov2,),
        ).fetchone()[0]
        assert remaining == 2

    def test_delete_measurements_noop_when_empty(self, store):
        from percell3.core import queries

        count = queries.delete_measurements_for_fov_threshold(store._conn, 999, 999)
        assert count == 0

        count = queries.delete_measurements_for_fov_segmentation(store._conn, 999, 999)
        assert count == 0

    def test_delete_cells_noop_when_empty(self, store):
        from percell3.core import queries

        count = queries.delete_cells_for_fov_segmentation(store._conn, 999, 999)
        assert count == 0
