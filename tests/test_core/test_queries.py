"""Tests for percell3.core.queries."""

import pytest

from percell3.core.exceptions import (
    BioRepNotFoundError,
    ChannelNotFoundError,
    ConditionNotFoundError,
    DuplicateError,
    FovNotFoundError,
)
from percell3.core.models import CellRecord, MeasurementRecord
from percell3.core import queries


class TestChannelQueries:
    def test_insert_and_select(self, db_conn):
        cid = queries.insert_channel(db_conn, "DAPI", role="nucleus", color="#0000FF")
        assert cid >= 1
        channels = queries.select_channels(db_conn)
        assert len(channels) == 1
        assert channels[0].name == "DAPI"
        assert channels[0].role == "nucleus"

    def test_display_order_increments(self, db_conn):
        queries.insert_channel(db_conn, "DAPI")
        queries.insert_channel(db_conn, "GFP")
        channels = queries.select_channels(db_conn)
        assert channels[0].display_order == 0
        assert channels[1].display_order == 1

    def test_select_by_name(self, db_conn):
        queries.insert_channel(db_conn, "DAPI", color="#0000FF")
        ch = queries.select_channel_by_name(db_conn, "DAPI")
        assert ch.color == "#0000FF"

    def test_select_by_name_not_found(self, db_conn):
        with pytest.raises(ChannelNotFoundError):
            queries.select_channel_by_name(db_conn, "NOPE")

    def test_duplicate_raises(self, db_conn):
        queries.insert_channel(db_conn, "DAPI")
        with pytest.raises(DuplicateError):
            queries.insert_channel(db_conn, "DAPI")


class TestConditionQueries:
    def test_insert_and_select(self, db_conn):
        cid = queries.insert_condition(db_conn, "control")
        assert cid >= 1
        names = queries.select_conditions(db_conn)
        assert names == ["control"]

    def test_multiple_conditions(self, db_conn):
        queries.insert_condition(db_conn, "control")
        queries.insert_condition(db_conn, "treated")
        assert queries.select_conditions(db_conn) == ["control", "treated"]

    def test_duplicate_raises(self, db_conn):
        queries.insert_condition(db_conn, "control")
        with pytest.raises(DuplicateError):
            queries.insert_condition(db_conn, "control")

    def test_select_condition_id(self, db_conn):
        cid = queries.insert_condition(db_conn, "control")
        assert queries.select_condition_id(db_conn, "control") == cid

    def test_select_condition_id_not_found(self, db_conn):
        with pytest.raises(ConditionNotFoundError):
            queries.select_condition_id(db_conn, "nope")


class TestTimepointQueries:
    def test_insert_and_select(self, db_conn):
        tid = queries.insert_timepoint(db_conn, "t0", time_seconds=0.0)
        assert tid >= 1
        assert queries.select_timepoints(db_conn) == ["t0"]

    def test_select_id(self, db_conn):
        tid = queries.insert_timepoint(db_conn, "t0")
        assert queries.select_timepoint_id(db_conn, "t0") == tid

    def test_select_id_not_found(self, db_conn):
        assert queries.select_timepoint_id(db_conn, "nope") is None


class TestBioRepQueries:
    def test_default_bio_rep_exists(self, db_conn):
        """Schema creates default N1 bio rep."""
        reps = queries.select_bio_reps(db_conn)
        assert reps == ["N1"]

    def test_insert_and_select(self, db_conn):
        bid = queries.insert_bio_rep(db_conn, "N2")
        assert bid >= 1
        reps = queries.select_bio_reps(db_conn)
        assert reps == ["N1", "N2"]

    def test_select_by_name(self, db_conn):
        row = queries.select_bio_rep_by_name(db_conn, "N1")
        assert row["name"] == "N1"

    def test_select_by_name_not_found(self, db_conn):
        with pytest.raises(BioRepNotFoundError):
            queries.select_bio_rep_by_name(db_conn, "NOPE")

    def test_select_by_name_returns_id(self, db_conn):
        row = queries.select_bio_rep_by_name(db_conn, "N1")
        assert row["id"] >= 1

    def test_duplicate_raises(self, db_conn):
        with pytest.raises(DuplicateError):
            queries.insert_bio_rep(db_conn, "N1")

    def test_fov_with_bio_rep_id(self, db_conn):
        """FOVs correctly store and query bio_rep_id."""
        cid = queries.insert_condition(db_conn, "control")
        n2_id = queries.insert_bio_rep(db_conn, "N2")

        queries.insert_fov(db_conn, "r1", condition_id=cid, bio_rep_id=1)  # N1
        queries.insert_fov(db_conn, "r2", condition_id=cid, bio_rep_id=n2_id)

        n1_fovs = queries.select_fovs(db_conn, bio_rep_id=1)
        assert len(n1_fovs) == 1
        assert n1_fovs[0].name == "r1"
        assert n1_fovs[0].bio_rep == "N1"

        n2_fovs = queries.select_fovs(db_conn, bio_rep_id=n2_id)
        assert len(n2_fovs) == 1
        assert n2_fovs[0].name == "r2"
        assert n2_fovs[0].bio_rep == "N2"

    def test_same_fov_name_different_bio_reps(self, db_conn):
        """Same FOV name allowed in different bio reps."""
        cid = queries.insert_condition(db_conn, "control")
        n2_id = queries.insert_bio_rep(db_conn, "N2")

        queries.insert_fov(db_conn, "r1", condition_id=cid, bio_rep_id=1)
        queries.insert_fov(db_conn, "r1", condition_id=cid, bio_rep_id=n2_id)
        all_fovs = queries.select_fovs(db_conn, condition_id=cid)
        assert len(all_fovs) == 2

    def test_cells_include_bio_rep_name(self, db_conn):
        """select_cells returns bio_rep_name column."""
        ch_id = queries.insert_channel(db_conn, "DAPI")
        cid = queries.insert_condition(db_conn, "control")
        fov_id = queries.insert_fov(db_conn, "r1", condition_id=cid, bio_rep_id=1)
        seg_id = queries.insert_segmentation_run(db_conn, ch_id, "cyto3")
        cells = [
            CellRecord(
                fov_id=fov_id, segmentation_id=seg_id, label_value=1,
                centroid_x=100, centroid_y=200,
                bbox_x=80, bbox_y=180, bbox_w=40, bbox_h=40,
                area_pixels=1200,
            )
        ]
        queries.insert_cells(db_conn, cells)
        rows = queries.select_cells(db_conn, condition_id=cid)
        assert rows[0]["bio_rep_name"] == "N1"

    def test_count_cells_filter_bio_rep(self, db_conn):
        """count_cells can filter by bio_rep_id."""
        ch_id = queries.insert_channel(db_conn, "DAPI")
        cid = queries.insert_condition(db_conn, "control")
        n2_id = queries.insert_bio_rep(db_conn, "N2")
        fov1 = queries.insert_fov(db_conn, "r1", condition_id=cid, bio_rep_id=1)
        fov2 = queries.insert_fov(db_conn, "r2", condition_id=cid, bio_rep_id=n2_id)
        seg_id = queries.insert_segmentation_run(db_conn, ch_id, "cyto3")

        cells_n1 = [
            CellRecord(
                fov_id=fov1, segmentation_id=seg_id, label_value=i,
                centroid_x=100, centroid_y=200,
                bbox_x=80, bbox_y=180, bbox_w=40, bbox_h=40,
                area_pixels=1200,
            )
            for i in range(1, 4)
        ]
        cells_n2 = [
            CellRecord(
                fov_id=fov2, segmentation_id=seg_id, label_value=i,
                centroid_x=100, centroid_y=200,
                bbox_x=80, bbox_y=180, bbox_w=40, bbox_h=40,
                area_pixels=1200,
            )
            for i in range(1, 6)
        ]
        queries.insert_cells(db_conn, cells_n1)
        queries.insert_cells(db_conn, cells_n2)

        assert queries.count_cells(db_conn, bio_rep_id=1) == 3
        assert queries.count_cells(db_conn, bio_rep_id=n2_id) == 5
        assert queries.count_cells(db_conn) == 8


class TestFovQueries:
    def test_insert_and_select(self, db_conn):
        cid = queries.insert_condition(db_conn, "control")
        rid = queries.insert_fov(db_conn, "r1", condition_id=cid, bio_rep_id=1, width=2048, height=2048)
        assert rid >= 1
        fovs = queries.select_fovs(db_conn, condition_id=cid)
        assert len(fovs) == 1
        assert fovs[0].name == "r1"
        assert fovs[0].condition == "control"
        assert fovs[0].width == 2048

    def test_select_by_name(self, db_conn):
        cid = queries.insert_condition(db_conn, "control")
        queries.insert_fov(db_conn, "r1", condition_id=cid, bio_rep_id=1)
        r = queries.select_fov_by_name(db_conn, "r1", condition_id=cid)
        assert r.name == "r1"

    def test_select_by_name_not_found(self, db_conn):
        cid = queries.insert_condition(db_conn, "control")
        with pytest.raises(FovNotFoundError):
            queries.select_fov_by_name(db_conn, "nope", condition_id=cid)

    def test_duplicate_fov_same_condition(self, db_conn):
        cid = queries.insert_condition(db_conn, "control")
        queries.insert_fov(db_conn, "r1", condition_id=cid, bio_rep_id=1)
        with pytest.raises(DuplicateError):
            queries.insert_fov(db_conn, "r1", condition_id=cid, bio_rep_id=1)

    def test_same_name_different_condition(self, db_conn):
        c1 = queries.insert_condition(db_conn, "control")
        c2 = queries.insert_condition(db_conn, "treated")
        queries.insert_fov(db_conn, "r1", condition_id=c1, bio_rep_id=1)
        queries.insert_fov(db_conn, "r1", condition_id=c2, bio_rep_id=1)
        assert len(queries.select_fovs(db_conn)) == 2

    def test_with_timepoint(self, db_conn):
        cid = queries.insert_condition(db_conn, "control")
        tid = queries.insert_timepoint(db_conn, "t0")
        queries.insert_fov(db_conn, "r1", condition_id=cid, bio_rep_id=1, timepoint_id=tid)
        r = queries.select_fov_by_name(db_conn, "r1", condition_id=cid, timepoint_id=tid)
        assert r.timepoint == "t0"


class TestCellQueries:
    def _setup(self, db_conn):
        ch_id = queries.insert_channel(db_conn, "DAPI", role="nucleus")
        cond_id = queries.insert_condition(db_conn, "control")
        fov_id = queries.insert_fov(db_conn, "r1", condition_id=cond_id, bio_rep_id=1)
        seg_id = queries.insert_segmentation_run(db_conn, ch_id, "cyto3")
        return cond_id, fov_id, seg_id

    def test_insert_and_select(self, db_conn):
        cond_id, fov_id, seg_id = self._setup(db_conn)
        cells = [
            CellRecord(
                fov_id=fov_id, segmentation_id=seg_id, label_value=i,
                centroid_x=100.0 + i, centroid_y=200.0 + i,
                bbox_x=80 + i, bbox_y=180 + i, bbox_w=40, bbox_h=40,
                area_pixels=1200.0 + i * 10,
            )
            for i in range(1, 6)
        ]
        ids = queries.insert_cells(db_conn, cells)
        assert len(ids) == 5

        rows = queries.select_cells(db_conn, condition_id=cond_id)
        assert len(rows) == 5

    def test_count(self, db_conn):
        cond_id, fov_id, seg_id = self._setup(db_conn)
        cells = [
            CellRecord(
                fov_id=fov_id, segmentation_id=seg_id, label_value=1,
                centroid_x=100, centroid_y=200,
                bbox_x=80, bbox_y=180, bbox_w=40, bbox_h=40,
                area_pixels=1200,
            )
        ]
        queries.insert_cells(db_conn, cells)
        assert queries.count_cells(db_conn) == 1

    def test_area_filter(self, db_conn):
        cond_id, fov_id, seg_id = self._setup(db_conn)
        cells = [
            CellRecord(
                fov_id=fov_id, segmentation_id=seg_id, label_value=i,
                centroid_x=100, centroid_y=200,
                bbox_x=80, bbox_y=180, bbox_w=40, bbox_h=40,
                area_pixels=1000.0 + i * 100,
            )
            for i in range(1, 11)
        ]
        queries.insert_cells(db_conn, cells)
        rows = queries.select_cells(db_conn, min_area=1500)
        assert all(r["area_pixels"] >= 1500 for r in rows)


class TestMeasurementQueries:
    def _setup(self, db_conn):
        ch_id = queries.insert_channel(db_conn, "GFP", role="signal")
        cond_id = queries.insert_condition(db_conn, "control")
        fov_id = queries.insert_fov(db_conn, "r1", condition_id=cond_id, bio_rep_id=1)
        seg_id = queries.insert_segmentation_run(db_conn, ch_id, "cyto3")
        cells = [
            CellRecord(
                fov_id=fov_id, segmentation_id=seg_id, label_value=i,
                centroid_x=100, centroid_y=200,
                bbox_x=80, bbox_y=180, bbox_w=40, bbox_h=40,
                area_pixels=1200,
            )
            for i in range(1, 4)
        ]
        cell_ids = queries.insert_cells(db_conn, cells)
        return ch_id, cell_ids

    def test_insert_and_select(self, db_conn):
        ch_id, cell_ids = self._setup(db_conn)
        measurements = [
            MeasurementRecord(cell_id=cid, channel_id=ch_id,
                              metric="mean_intensity", value=42.0 + cid)
            for cid in cell_ids
        ]
        queries.insert_measurements(db_conn, measurements)
        rows = queries.select_measurements(db_conn, channel_ids=[ch_id])
        assert len(rows) == 3
        assert all(r["metric"] == "mean_intensity" for r in rows)

    def test_filter_by_metric(self, db_conn):
        ch_id, cell_ids = self._setup(db_conn)
        measurements = []
        for cid in cell_ids:
            measurements.append(
                MeasurementRecord(cell_id=cid, channel_id=ch_id,
                                  metric="mean_intensity", value=42.0)
            )
            measurements.append(
                MeasurementRecord(cell_id=cid, channel_id=ch_id,
                                  metric="max_intensity", value=100.0)
            )
        queries.insert_measurements(db_conn, measurements)
        rows = queries.select_measurements(db_conn, metrics=["mean_intensity"])
        assert len(rows) == 3


class TestTagQueries:
    def _setup_cells(self, db_conn):
        ch_id = queries.insert_channel(db_conn, "DAPI")
        cond_id = queries.insert_condition(db_conn, "control")
        fov_id = queries.insert_fov(db_conn, "r1", condition_id=cond_id, bio_rep_id=1)
        seg_id = queries.insert_segmentation_run(db_conn, ch_id, "cyto3")
        cells = [
            CellRecord(
                fov_id=fov_id, segmentation_id=seg_id, label_value=i,
                centroid_x=100, centroid_y=200,
                bbox_x=80, bbox_y=180, bbox_w=40, bbox_h=40,
                area_pixels=1200,
            )
            for i in range(1, 4)
        ]
        return queries.insert_cells(db_conn, cells)

    def test_insert_tag(self, db_conn):
        tid = queries.insert_tag(db_conn, "positive", color="#00FF00")
        assert tid >= 1

    def test_tag_cells(self, db_conn):
        cell_ids = self._setup_cells(db_conn)
        tag_id = queries.insert_tag(db_conn, "positive")
        queries.insert_cell_tags(db_conn, cell_ids[:2], tag_id)
        rows = queries.select_cells(db_conn, tag_ids=[tag_id])
        assert len(rows) == 2

    def test_untag_cells(self, db_conn):
        cell_ids = self._setup_cells(db_conn)
        tag_id = queries.insert_tag(db_conn, "positive")
        queries.insert_cell_tags(db_conn, cell_ids, tag_id)
        queries.delete_cell_tags(db_conn, cell_ids[:1], tag_id)
        rows = queries.select_cells(db_conn, tag_ids=[tag_id])
        assert len(rows) == 2


class TestAnalysisRunQueries:
    def test_insert_and_complete(self, db_conn):
        run_id = queries.insert_analysis_run(db_conn, "intensity_grouping", {"threshold": 100})
        assert run_id >= 1
        queries.complete_analysis_run(db_conn, run_id, status="completed", cell_count=50)
        row = db_conn.execute(
            "SELECT status, cell_count FROM analysis_runs WHERE id = ?", (run_id,)
        ).fetchone()
        assert row["status"] == "completed"
        assert row["cell_count"] == 50


class TestEmptyListGuards:
    """Verify that passing empty lists doesn't crash with invalid SQL."""

    def _setup(self, db_conn):
        ch_id = queries.insert_channel(db_conn, "DAPI")
        cond_id = queries.insert_condition(db_conn, "control")
        fov_id = queries.insert_fov(db_conn, "r1", condition_id=cond_id, bio_rep_id=1)
        seg_id = queries.insert_segmentation_run(db_conn, ch_id, "cyto3")
        return ch_id, cond_id, fov_id, seg_id

    def test_delete_cell_tags_empty_list(self, db_conn):
        tag_id = queries.insert_tag(db_conn, "positive")
        queries.delete_cell_tags(db_conn, [], tag_id)  # should not crash

    def test_insert_cell_tags_empty_list(self, db_conn):
        tag_id = queries.insert_tag(db_conn, "positive")
        queries.insert_cell_tags(db_conn, [], tag_id)  # should not crash

    def test_insert_cells_empty_list(self, db_conn):
        result = queries.insert_cells(db_conn, [])
        assert result == []

    def test_select_measurements_empty_channel_ids(self, db_conn):
        rows = queries.select_measurements(db_conn, channel_ids=[])
        assert rows == []

    def test_select_cells_empty_tag_ids(self, db_conn):
        rows = queries.select_cells(db_conn, tag_ids=[])
        assert isinstance(rows, list)


class TestInsertCellsRollback:
    """Verify that insert_cells rolls back on failure."""

    def test_rollback_on_duplicate(self, db_conn):
        ch_id = queries.insert_channel(db_conn, "DAPI")
        cond_id = queries.insert_condition(db_conn, "control")
        fov_id = queries.insert_fov(db_conn, "r1", condition_id=cond_id, bio_rep_id=1)
        seg_id = queries.insert_segmentation_run(db_conn, ch_id, "cyto3")

        cells = [
            CellRecord(
                fov_id=fov_id, segmentation_id=seg_id, label_value=1,
                centroid_x=100, centroid_y=200,
                bbox_x=80, bbox_y=180, bbox_w=40, bbox_h=40, area_pixels=1200,
            ),
            CellRecord(
                fov_id=fov_id, segmentation_id=seg_id, label_value=1,  # duplicate
                centroid_x=100, centroid_y=200,
                bbox_x=80, bbox_y=180, bbox_w=40, bbox_h=40, area_pixels=1200,
            ),
        ]
        with pytest.raises(DuplicateError):
            queries.insert_cells(db_conn, cells)

        # After rollback, no cells should be in the table
        count = db_conn.execute("SELECT COUNT(*) FROM cells").fetchone()[0]
        assert count == 0
