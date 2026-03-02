"""Tests for percell3.core.queries."""

import pytest

from percell3.core.exceptions import (
    BioRepNotFoundError,
    ChannelNotFoundError,
    ConditionNotFoundError,
    DuplicateError,
    FovNotFoundError,
    SegmentationNotFoundError,
    ThresholdNotFoundError,
)
from percell3.core.models import CellRecord, MeasurementRecord, ParticleRecord
from percell3.core import queries


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_seg(db_conn, name="seg", seg_type="cellular", w=64, h=64,
              source_fov_id=None, source_channel=None, model_name="cyto3"):
    """Create a segmentation with sensible defaults."""
    return queries.insert_segmentation(
        db_conn, name, seg_type, w, h,
        source_fov_id=source_fov_id, source_channel=source_channel,
        model_name=model_name,
    )


def _make_thresh(db_conn, name="thr", method="otsu", w=64, h=64,
                 source_fov_id=None, source_channel=None):
    """Create a threshold with sensible defaults."""
    return queries.insert_threshold(
        db_conn, name, method, w, h,
        source_fov_id=source_fov_id, source_channel=source_channel,
    )


# ---------------------------------------------------------------------------
# Channel queries
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Condition queries
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Timepoint queries
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Bio rep queries
# ---------------------------------------------------------------------------


class TestBioRepQueries:
    def test_no_default_bio_rep(self, db_conn):
        """Schema no longer creates a default bio rep."""
        reps = queries.select_bio_reps(db_conn)
        assert reps == []

    def test_insert_and_select(self, db_conn):
        bid = queries.insert_bio_rep(db_conn, "N1")
        assert bid >= 1
        reps = queries.select_bio_reps(db_conn)
        assert reps == ["N1"]

    def test_select_by_name(self, db_conn):
        queries.insert_bio_rep(db_conn, "N1")
        row = queries.select_bio_rep_by_name(db_conn, "N1")
        assert row["name"] == "N1"

    def test_select_by_name_not_found(self, db_conn):
        with pytest.raises(BioRepNotFoundError):
            queries.select_bio_rep_by_name(db_conn, "NOPE")

    def test_select_by_name_returns_id(self, db_conn):
        queries.insert_bio_rep(db_conn, "N1")
        row = queries.select_bio_rep_by_name(db_conn, "N1")
        assert row["id"] >= 1

    def test_duplicate_raises(self, db_conn):
        queries.insert_bio_rep(db_conn, "N1")
        with pytest.raises(DuplicateError):
            queries.insert_bio_rep(db_conn, "N1")

    def test_experiment_global(self, db_conn):
        """Bio reps are experiment-global (one N1 shared across conditions)."""
        queries.insert_bio_rep(db_conn, "N1")
        queries.insert_bio_rep(db_conn, "N2")
        reps = queries.select_bio_reps(db_conn)
        assert reps == ["N1", "N2"]

    def test_fov_with_bio_rep_id(self, db_conn):
        """FOVs correctly store and query bio_rep_id."""
        cid = queries.insert_condition(db_conn, "control")
        n1_id = queries.insert_bio_rep(db_conn, "N1")
        n2_id = queries.insert_bio_rep(db_conn, "N2")

        queries.insert_fov(db_conn, "ctrl_N1_FOV_001", condition_id=cid, bio_rep_id=n1_id)
        queries.insert_fov(db_conn, "ctrl_N2_FOV_001", condition_id=cid, bio_rep_id=n2_id)

        n1_fovs = queries.select_fovs(db_conn, bio_rep_id=n1_id)
        assert len(n1_fovs) == 1
        assert n1_fovs[0].display_name == "ctrl_N1_FOV_001"
        assert n1_fovs[0].bio_rep == "N1"

        n2_fovs = queries.select_fovs(db_conn, bio_rep_id=n2_id)
        assert len(n2_fovs) == 1
        assert n2_fovs[0].display_name == "ctrl_N2_FOV_001"
        assert n2_fovs[0].bio_rep == "N2"

    def test_cells_include_bio_rep_name(self, db_conn):
        """select_cells returns bio_rep_name column."""
        queries.insert_channel(db_conn, "DAPI")
        cid = queries.insert_condition(db_conn, "control")
        br_id = queries.insert_bio_rep(db_conn, "N1")
        fov_id = queries.insert_fov(db_conn, "ctrl_N1_FOV_001", condition_id=cid, bio_rep_id=br_id)
        seg_id = _make_seg(db_conn, "seg", source_fov_id=fov_id, source_channel="DAPI")
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
        queries.insert_channel(db_conn, "DAPI")
        cid = queries.insert_condition(db_conn, "control")
        n1_id = queries.insert_bio_rep(db_conn, "N1")
        n2_id = queries.insert_bio_rep(db_conn, "N2")
        fov1 = queries.insert_fov(db_conn, "ctrl_N1_FOV_001", condition_id=cid, bio_rep_id=n1_id)
        fov2 = queries.insert_fov(db_conn, "ctrl_N2_FOV_001", condition_id=cid, bio_rep_id=n2_id)
        seg_id1 = _make_seg(db_conn, "seg1", source_fov_id=fov1)
        seg_id2 = _make_seg(db_conn, "seg2", source_fov_id=fov2)

        cells_n1 = [
            CellRecord(
                fov_id=fov1, segmentation_id=seg_id1, label_value=i,
                centroid_x=100, centroid_y=200,
                bbox_x=80, bbox_y=180, bbox_w=40, bbox_h=40,
                area_pixels=1200,
            )
            for i in range(1, 4)
        ]
        cells_n2 = [
            CellRecord(
                fov_id=fov2, segmentation_id=seg_id2, label_value=i,
                centroid_x=100, centroid_y=200,
                bbox_x=80, bbox_y=180, bbox_w=40, bbox_h=40,
                area_pixels=1200,
            )
            for i in range(1, 6)
        ]
        queries.insert_cells(db_conn, cells_n1)
        queries.insert_cells(db_conn, cells_n2)

        assert queries.count_cells(db_conn, bio_rep_id=n1_id) == 3
        assert queries.count_cells(db_conn, bio_rep_id=n2_id) == 5
        assert queries.count_cells(db_conn) == 8


# ---------------------------------------------------------------------------
# FOV queries
# ---------------------------------------------------------------------------


class TestFovQueries:
    def _make_fov_deps(self, db_conn, condition_name="control"):
        """Helper: create condition + N1 bio rep, return (cond_id, br_id)."""
        cid = queries.insert_condition(db_conn, condition_name)
        br_id = queries.insert_bio_rep(db_conn, "N1")
        return cid, br_id

    def test_insert_and_select(self, db_conn):
        cid, br_id = self._make_fov_deps(db_conn)
        rid = queries.insert_fov(
            db_conn, "ctrl_N1_FOV_001", condition_id=cid, bio_rep_id=br_id,
            width=2048, height=2048,
        )
        assert rid >= 1
        fovs = queries.select_fovs(db_conn, condition_id=cid)
        assert len(fovs) == 1
        assert fovs[0].display_name == "ctrl_N1_FOV_001"
        assert fovs[0].condition == "control"
        assert fovs[0].width == 2048

    def test_select_by_id(self, db_conn):
        cid, br_id = self._make_fov_deps(db_conn)
        fov_id = queries.insert_fov(
            db_conn, "ctrl_N1_FOV_001", condition_id=cid, bio_rep_id=br_id,
        )
        r = queries.select_fov_by_id(db_conn, fov_id)
        assert r.display_name == "ctrl_N1_FOV_001"

    def test_select_by_display_name(self, db_conn):
        cid, br_id = self._make_fov_deps(db_conn)
        queries.insert_fov(
            db_conn, "ctrl_N1_FOV_001", condition_id=cid, bio_rep_id=br_id,
        )
        r = queries.select_fov_by_display_name(db_conn, "ctrl_N1_FOV_001")
        assert r.display_name == "ctrl_N1_FOV_001"

    def test_select_by_id_not_found(self, db_conn):
        with pytest.raises(FovNotFoundError):
            queries.select_fov_by_id(db_conn, 9999)

    def test_duplicate_display_name_raises(self, db_conn):
        cid, br_id = self._make_fov_deps(db_conn)
        queries.insert_fov(db_conn, "FOV_A", condition_id=cid, bio_rep_id=br_id)
        with pytest.raises(DuplicateError):
            queries.insert_fov(db_conn, "FOV_A", condition_id=cid, bio_rep_id=br_id)

    def test_with_timepoint(self, db_conn):
        cid, br_id = self._make_fov_deps(db_conn)
        tid = queries.insert_timepoint(db_conn, "t0")
        fov_id = queries.insert_fov(
            db_conn, "ctrl_N1_FOV_001", condition_id=cid, bio_rep_id=br_id,
            timepoint_id=tid,
        )
        r = queries.select_fov_by_id(db_conn, fov_id)
        assert r.timepoint == "t0"


# ---------------------------------------------------------------------------
# Segmentation queries (NEW)
# ---------------------------------------------------------------------------


class TestSegmentationQueries:
    def test_insert_and_select(self, db_conn):
        seg_id = queries.insert_segmentation(
            db_conn, "cellpose_seg", "cellular", 2048, 2048,
            model_name="cyto3",
        )
        assert seg_id >= 1
        segs = queries.select_segmentations(db_conn)
        assert len(segs) == 1
        assert segs[0].name == "cellpose_seg"
        assert segs[0].seg_type == "cellular"
        assert segs[0].model_name == "cyto3"
        assert segs[0].width == 2048
        assert segs[0].height == 2048
        assert segs[0].cell_count == 0

    def test_select_by_id(self, db_conn):
        seg_id = _make_seg(db_conn, "my_seg")
        seg = queries.select_segmentation(db_conn, seg_id)
        assert seg.id == seg_id
        assert seg.name == "my_seg"

    def test_select_by_id_not_found(self, db_conn):
        with pytest.raises(SegmentationNotFoundError):
            queries.select_segmentation(db_conn, 9999)

    def test_filter_by_type(self, db_conn):
        _make_seg(db_conn, "cell_seg", seg_type="cellular")
        _make_seg(db_conn, "wf_seg", seg_type="whole_field")
        cellular = queries.select_segmentations(db_conn, seg_type="cellular")
        assert len(cellular) == 1
        assert cellular[0].name == "cell_seg"

    def test_filter_by_dimensions(self, db_conn):
        _make_seg(db_conn, "small", w=64, h=64)
        _make_seg(db_conn, "large", w=2048, h=2048)
        large = queries.select_segmentations(db_conn, width=2048, height=2048)
        assert len(large) == 1
        assert large[0].name == "large"

    def test_with_source_fov_and_channel(self, db_conn):
        cid = queries.insert_condition(db_conn, "ctrl")
        br_id = queries.insert_bio_rep(db_conn, "N1")
        fov_id = queries.insert_fov(db_conn, "FOV_1", condition_id=cid, bio_rep_id=br_id)
        seg_id = queries.insert_segmentation(
            db_conn, "seg", "cellular", 64, 64,
            source_fov_id=fov_id, source_channel="DAPI",
        )
        seg = queries.select_segmentation(db_conn, seg_id)
        assert seg.source_fov_id == fov_id
        assert seg.source_channel == "DAPI"

    def test_with_parameters(self, db_conn):
        seg_id = queries.insert_segmentation(
            db_conn, "seg", "cellular", 64, 64,
            parameters={"diameter": 30, "flow_threshold": 0.4},
        )
        seg = queries.select_segmentation(db_conn, seg_id)
        assert seg.parameters["diameter"] == 30

    def test_duplicate_name_raises(self, db_conn):
        _make_seg(db_conn, "same_name")
        with pytest.raises(DuplicateError):
            _make_seg(db_conn, "same_name")

    def test_rename(self, db_conn):
        seg_id = _make_seg(db_conn, "old_name")
        queries.rename_segmentation(db_conn, seg_id, "new_name")
        seg = queries.select_segmentation(db_conn, seg_id)
        assert seg.name == "new_name"

    def test_rename_duplicate_raises(self, db_conn):
        _make_seg(db_conn, "name_a")
        seg_id = _make_seg(db_conn, "name_b")
        with pytest.raises(DuplicateError):
            queries.rename_segmentation(db_conn, seg_id, "name_a")

    def test_delete(self, db_conn):
        seg_id = _make_seg(db_conn, "to_delete")
        queries.delete_segmentation(db_conn, seg_id)
        segs = queries.select_segmentations(db_conn)
        assert len(segs) == 0

    def test_update_cell_count(self, db_conn):
        seg_id = _make_seg(db_conn, "seg")
        queries.update_segmentation_cell_count(db_conn, seg_id, 42)
        seg = queries.select_segmentation(db_conn, seg_id)
        assert seg.cell_count == 42


# ---------------------------------------------------------------------------
# Threshold queries (NEW)
# ---------------------------------------------------------------------------


class TestThresholdQueries:
    def test_insert_and_select(self, db_conn):
        thr_id = queries.insert_threshold(
            db_conn, "otsu_thr", "otsu", 2048, 2048,
            source_channel="GFP",
        )
        assert thr_id >= 1
        thrs = queries.select_thresholds(db_conn)
        assert len(thrs) == 1
        assert thrs[0].name == "otsu_thr"
        assert thrs[0].method == "otsu"
        assert thrs[0].width == 2048

    def test_select_by_id(self, db_conn):
        thr_id = _make_thresh(db_conn, "my_thr")
        thr = queries.select_threshold(db_conn, thr_id)
        assert thr.id == thr_id
        assert thr.name == "my_thr"

    def test_select_by_id_not_found(self, db_conn):
        with pytest.raises(ThresholdNotFoundError):
            queries.select_threshold(db_conn, 9999)

    def test_filter_by_dimensions(self, db_conn):
        _make_thresh(db_conn, "small", w=64, h=64)
        _make_thresh(db_conn, "large", w=2048, h=2048)
        large = queries.select_thresholds(db_conn, width=2048, height=2048)
        assert len(large) == 1
        assert large[0].name == "large"

    def test_with_source_and_grouping_channel(self, db_conn):
        thr_id = queries.insert_threshold(
            db_conn, "thr", "otsu", 64, 64,
            source_channel="GFP", grouping_channel="DAPI",
        )
        thr = queries.select_threshold(db_conn, thr_id)
        assert thr.source_channel == "GFP"
        assert thr.grouping_channel == "DAPI"

    def test_with_parameters(self, db_conn):
        thr_id = queries.insert_threshold(
            db_conn, "thr", "manual", 64, 64,
            parameters={"value": 128},
        )
        thr = queries.select_threshold(db_conn, thr_id)
        assert thr.parameters["value"] == 128

    def test_duplicate_name_raises(self, db_conn):
        _make_thresh(db_conn, "same_name")
        with pytest.raises(DuplicateError):
            _make_thresh(db_conn, "same_name")

    def test_rename(self, db_conn):
        thr_id = _make_thresh(db_conn, "old_name")
        queries.rename_threshold(db_conn, thr_id, "new_name")
        thr = queries.select_threshold(db_conn, thr_id)
        assert thr.name == "new_name"

    def test_rename_duplicate_raises(self, db_conn):
        _make_thresh(db_conn, "name_a")
        thr_id = _make_thresh(db_conn, "name_b")
        with pytest.raises(DuplicateError):
            queries.rename_threshold(db_conn, thr_id, "name_a")

    def test_delete(self, db_conn):
        thr_id = _make_thresh(db_conn, "to_delete")
        queries.delete_threshold(db_conn, thr_id)
        thrs = queries.select_thresholds(db_conn)
        assert len(thrs) == 0

    def test_update_threshold_value(self, db_conn):
        thr_id = _make_thresh(db_conn, "thr")
        queries.update_threshold_value(db_conn, thr_id, 128.5)
        thr = queries.select_threshold(db_conn, thr_id)
        assert thr.threshold_value == 128.5


# ---------------------------------------------------------------------------
# Cell queries
# ---------------------------------------------------------------------------


class TestCellQueries:
    def _setup(self, db_conn):
        queries.insert_channel(db_conn, "DAPI", role="nucleus")
        cond_id = queries.insert_condition(db_conn, "control")
        br_id = queries.insert_bio_rep(db_conn, "N1")
        fov_id = queries.insert_fov(db_conn, "ctrl_N1_FOV_001", condition_id=cond_id, bio_rep_id=br_id)
        seg_id = _make_seg(db_conn, "seg", source_fov_id=fov_id, source_channel="DAPI")
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


# ---------------------------------------------------------------------------
# Measurement queries
# ---------------------------------------------------------------------------


class TestMeasurementQueries:
    def _setup(self, db_conn):
        ch_id = queries.insert_channel(db_conn, "GFP", role="signal")
        cond_id = queries.insert_condition(db_conn, "control")
        br_id = queries.insert_bio_rep(db_conn, "N1")
        fov_id = queries.insert_fov(db_conn, "ctrl_N1_FOV_001", condition_id=cond_id, bio_rep_id=br_id)
        seg_id = _make_seg(db_conn, "seg", source_fov_id=fov_id, source_channel="GFP")
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
        return ch_id, fov_id, seg_id, cell_ids

    def test_insert_and_select(self, db_conn):
        ch_id, fov_id, seg_id, cell_ids = self._setup(db_conn)
        measurements = [
            MeasurementRecord(cell_id=cid, channel_id=ch_id,
                              metric="mean_intensity", value=42.0 + cid,
                              segmentation_id=seg_id)
            for cid in cell_ids
        ]
        queries.insert_measurements(db_conn, measurements)
        rows = queries.select_measurements(db_conn, channel_ids=[ch_id])
        assert len(rows) == 3
        assert all(r["metric"] == "mean_intensity" for r in rows)

    def test_filter_by_metric(self, db_conn):
        ch_id, fov_id, seg_id, cell_ids = self._setup(db_conn)
        measurements = []
        for cid in cell_ids:
            measurements.append(
                MeasurementRecord(cell_id=cid, channel_id=ch_id,
                                  metric="mean_intensity", value=42.0,
                                  segmentation_id=seg_id)
            )
            measurements.append(
                MeasurementRecord(cell_id=cid, channel_id=ch_id,
                                  metric="max_intensity", value=100.0,
                                  segmentation_id=seg_id)
            )
        queries.insert_measurements(db_conn, measurements)
        rows = queries.select_measurements(db_conn, metrics=["mean_intensity"])
        assert len(rows) == 3

    def test_insert_with_scope(self, db_conn):
        ch_id, fov_id, seg_id, cell_ids = self._setup(db_conn)
        measurements = [
            MeasurementRecord(
                cell_id=cell_ids[0], channel_id=ch_id,
                metric="mean_intensity", value=42.0, scope="whole_cell",
                segmentation_id=seg_id,
            ),
            MeasurementRecord(
                cell_id=cell_ids[0], channel_id=ch_id,
                metric="mean_intensity", value=30.0, scope="mask_inside",
                segmentation_id=seg_id,
            ),
            MeasurementRecord(
                cell_id=cell_ids[0], channel_id=ch_id,
                metric="mean_intensity", value=12.0, scope="mask_outside",
                segmentation_id=seg_id,
            ),
        ]
        queries.insert_measurements(db_conn, measurements)
        rows = queries.select_measurements(db_conn, cell_ids=[cell_ids[0]])
        assert len(rows) == 3
        scopes = {r["scope"] for r in rows}
        assert scopes == {"whole_cell", "mask_inside", "mask_outside"}

    def test_filter_by_scope(self, db_conn):
        ch_id, fov_id, seg_id, cell_ids = self._setup(db_conn)
        measurements = [
            MeasurementRecord(
                cell_id=cell_ids[0], channel_id=ch_id,
                metric="mean_intensity", value=42.0, scope="whole_cell",
                segmentation_id=seg_id,
            ),
            MeasurementRecord(
                cell_id=cell_ids[0], channel_id=ch_id,
                metric="mean_intensity", value=30.0, scope="mask_inside",
                segmentation_id=seg_id,
            ),
        ]
        queries.insert_measurements(db_conn, measurements)
        rows = queries.select_measurements(db_conn, scope="mask_inside")
        assert len(rows) == 1
        assert rows[0]["scope"] == "mask_inside"
        assert rows[0]["value"] == 30.0

    def test_scope_default_is_whole_cell(self, db_conn):
        ch_id, fov_id, seg_id, cell_ids = self._setup(db_conn)
        m = MeasurementRecord(
            cell_id=cell_ids[0], channel_id=ch_id,
            metric="mean_intensity", value=42.0,
            segmentation_id=seg_id,
        )
        queries.insert_measurements(db_conn, [m])
        rows = queries.select_measurements(db_conn)
        assert rows[0]["scope"] == "whole_cell"
        assert rows[0]["threshold_id"] is None

    def test_overwrite_by_scope(self, db_conn):
        """INSERT OR REPLACE respects scope in unique constraint."""
        ch_id, fov_id, seg_id, cell_ids = self._setup(db_conn)
        m1 = MeasurementRecord(
            cell_id=cell_ids[0], channel_id=ch_id,
            metric="mean_intensity", value=42.0, scope="whole_cell",
            segmentation_id=seg_id,
        )
        queries.insert_measurements(db_conn, [m1])
        m2 = MeasurementRecord(
            cell_id=cell_ids[0], channel_id=ch_id,
            metric="mean_intensity", value=30.0, scope="mask_inside",
            segmentation_id=seg_id,
        )
        queries.insert_measurements(db_conn, [m2])
        rows = queries.select_measurements(db_conn, cell_ids=[cell_ids[0]])
        assert len(rows) == 2

        m3 = MeasurementRecord(
            cell_id=cell_ids[0], channel_id=ch_id,
            metric="mean_intensity", value=99.0, scope="whole_cell",
            segmentation_id=seg_id,
        )
        queries.insert_measurements(db_conn, [m3])
        rows = queries.select_measurements(
            db_conn, cell_ids=[cell_ids[0]], scope="whole_cell",
        )
        assert len(rows) == 1
        assert rows[0]["value"] == 99.0

    def test_threshold_id_stored(self, db_conn):
        ch_id, fov_id, seg_id, cell_ids = self._setup(db_conn)
        thr_id = _make_thresh(db_conn, "thr", source_fov_id=fov_id, source_channel="GFP")
        m = MeasurementRecord(
            cell_id=cell_ids[0], channel_id=ch_id,
            metric="mean_intensity", value=30.0,
            scope="mask_inside", segmentation_id=seg_id,
            threshold_id=thr_id,
        )
        queries.insert_measurements(db_conn, [m])
        rows = queries.select_measurements(db_conn, scope="mask_inside")
        assert rows[0]["threshold_id"] == thr_id

    def test_segmentation_id_stored(self, db_conn):
        ch_id, fov_id, seg_id, cell_ids = self._setup(db_conn)
        m = MeasurementRecord(
            cell_id=cell_ids[0], channel_id=ch_id,
            metric="mean_intensity", value=50.0,
            segmentation_id=seg_id,
        )
        queries.insert_measurements(db_conn, [m])
        rows = queries.select_measurements(db_conn)
        assert rows[0]["segmentation_id"] == seg_id


# ---------------------------------------------------------------------------
# Tag queries
# ---------------------------------------------------------------------------


class TestTagQueries:
    def _setup_cells(self, db_conn):
        queries.insert_channel(db_conn, "DAPI")
        cond_id = queries.insert_condition(db_conn, "control")
        br_id = queries.insert_bio_rep(db_conn, "N1")
        fov_id = queries.insert_fov(db_conn, "ctrl_N1_FOV_001", condition_id=cond_id, bio_rep_id=br_id)
        seg_id = _make_seg(db_conn, "seg", source_fov_id=fov_id)
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


# ---------------------------------------------------------------------------
# Analysis run queries
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Analysis config queries (NEW)
# ---------------------------------------------------------------------------


class TestAnalysisConfigQueries:
    def test_get_or_create(self, db_conn):
        config = queries.get_or_create_analysis_config(db_conn)
        assert config.id >= 1
        assert config.experiment_id == 1

    def test_idempotent(self, db_conn):
        config1 = queries.get_or_create_analysis_config(db_conn)
        config2 = queries.get_or_create_analysis_config(db_conn)
        assert config1.id == config2.id


# ---------------------------------------------------------------------------
# FOV config queries (NEW)
# ---------------------------------------------------------------------------


class TestFovConfigQueries:
    def _setup(self, db_conn):
        cid = queries.insert_condition(db_conn, "ctrl")
        br_id = queries.insert_bio_rep(db_conn, "N1")
        fov_id = queries.insert_fov(
            db_conn, "ctrl_N1_FOV_001", condition_id=cid, bio_rep_id=br_id,
        )
        seg_id = _make_seg(db_conn, "seg")
        thr_id = _make_thresh(db_conn, "thr")
        config = queries.get_or_create_analysis_config(db_conn)
        return fov_id, seg_id, thr_id, config.id

    def test_insert_and_select(self, db_conn):
        fov_id, seg_id, thr_id, config_id = self._setup(db_conn)
        entry_id = queries.insert_fov_config_entry(
            db_conn, config_id, fov_id, seg_id, thr_id,
        )
        assert entry_id >= 1

        entries = queries.select_fov_config(db_conn, config_id)
        assert len(entries) == 1
        e = entries[0]
        assert e.fov_id == fov_id
        assert e.segmentation_id == seg_id
        assert e.threshold_id == thr_id
        assert e.scopes == ["whole_cell"]

    def test_select_by_fov(self, db_conn):
        fov_id, seg_id, thr_id, config_id = self._setup(db_conn)
        queries.insert_fov_config_entry(db_conn, config_id, fov_id, seg_id, thr_id)
        entries = queries.select_fov_config(db_conn, config_id, fov_id=fov_id)
        assert len(entries) == 1

    def test_without_threshold(self, db_conn):
        fov_id, seg_id, _, config_id = self._setup(db_conn)
        entry_id = queries.insert_fov_config_entry(
            db_conn, config_id, fov_id, seg_id,
        )
        entries = queries.select_fov_config(db_conn, config_id)
        assert entries[0].threshold_id is None

    def test_custom_scopes(self, db_conn):
        fov_id, seg_id, thr_id, config_id = self._setup(db_conn)
        queries.insert_fov_config_entry(
            db_conn, config_id, fov_id, seg_id, thr_id,
            scopes=["whole_cell", "mask_inside", "mask_outside"],
        )
        entries = queries.select_fov_config(db_conn, config_id)
        assert set(entries[0].scopes) == {"whole_cell", "mask_inside", "mask_outside"}

    def test_update_entry(self, db_conn):
        fov_id, seg_id, thr_id, config_id = self._setup(db_conn)
        entry_id = queries.insert_fov_config_entry(
            db_conn, config_id, fov_id, seg_id,
        )
        queries.update_fov_config_entry(
            db_conn, entry_id, threshold_id=thr_id,
            scopes=["mask_inside"],
        )
        entries = queries.select_fov_config(db_conn, config_id)
        assert entries[0].threshold_id == thr_id
        assert entries[0].scopes == ["mask_inside"]

    def test_delete_entry(self, db_conn):
        fov_id, seg_id, thr_id, config_id = self._setup(db_conn)
        entry_id = queries.insert_fov_config_entry(
            db_conn, config_id, fov_id, seg_id, thr_id,
        )
        queries.delete_fov_config_entry(db_conn, entry_id)
        entries = queries.select_fov_config(db_conn, config_id)
        assert len(entries) == 0

    def test_delete_for_fov(self, db_conn):
        fov_id, seg_id, thr_id, config_id = self._setup(db_conn)
        queries.insert_fov_config_entry(db_conn, config_id, fov_id, seg_id, thr_id)
        queries.insert_fov_config_entry(db_conn, config_id, fov_id, seg_id)
        assert len(queries.select_fov_config(db_conn, config_id)) == 2

        queries.delete_fov_config_for_fov(db_conn, config_id, fov_id)
        assert len(queries.select_fov_config(db_conn, config_id)) == 0

    def test_multiple_fovs(self, db_conn):
        cid = queries.insert_condition(db_conn, "ctrl")
        br_id = queries.insert_bio_rep(db_conn, "N1")
        fov1 = queries.insert_fov(db_conn, "FOV_1", condition_id=cid, bio_rep_id=br_id)
        fov2 = queries.insert_fov(db_conn, "FOV_2", condition_id=cid, bio_rep_id=br_id)
        seg_id = _make_seg(db_conn, "seg")
        config = queries.get_or_create_analysis_config(db_conn)

        queries.insert_fov_config_entry(db_conn, config.id, fov1, seg_id)
        queries.insert_fov_config_entry(db_conn, config.id, fov2, seg_id)

        all_entries = queries.select_fov_config(db_conn, config.id)
        assert len(all_entries) == 2

        fov1_entries = queries.select_fov_config(db_conn, config.id, fov_id=fov1)
        assert len(fov1_entries) == 1
        assert fov1_entries[0].fov_id == fov1


# ---------------------------------------------------------------------------
# Empty list guards
# ---------------------------------------------------------------------------


class TestEmptyListGuards:
    """Verify that passing empty lists doesn't crash with invalid SQL."""

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


# ---------------------------------------------------------------------------
# Insert cells rollback
# ---------------------------------------------------------------------------


class TestInsertCellsRollback:
    """Verify that insert_cells rolls back on failure."""

    def test_rollback_on_duplicate(self, db_conn):
        cond_id = queries.insert_condition(db_conn, "control")
        br_id = queries.insert_bio_rep(db_conn, "N1")
        fov_id = queries.insert_fov(db_conn, "ctrl_N1_FOV_001", condition_id=cond_id, bio_rep_id=br_id)
        seg_id = _make_seg(db_conn, "seg", source_fov_id=fov_id)

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

        count = db_conn.execute("SELECT COUNT(*) FROM cells").fetchone()[0]
        assert count == 0


# ---------------------------------------------------------------------------
# Rename queries
# ---------------------------------------------------------------------------


class TestRenameQueries:
    def test_rename_experiment(self, db_conn):
        queries.rename_experiment(db_conn, "New Name")
        assert queries.get_experiment_name(db_conn) == "New Name"

    def test_rename_condition(self, db_conn):
        queries.insert_condition(db_conn, "control")
        queries.rename_condition(db_conn, "control", "ctrl")
        conds = queries.select_conditions(db_conn)
        assert "ctrl" in conds
        assert "control" not in conds

    def test_rename_condition_not_found(self, db_conn):
        with pytest.raises(ConditionNotFoundError):
            queries.rename_condition(db_conn, "NOPE", "new")

    def test_rename_condition_duplicate(self, db_conn):
        queries.insert_condition(db_conn, "control")
        queries.insert_condition(db_conn, "treated")
        with pytest.raises(DuplicateError):
            queries.rename_condition(db_conn, "control", "treated")

    def test_rename_channel(self, db_conn):
        queries.insert_channel(db_conn, "DAPI")
        queries.rename_channel(db_conn, "DAPI", "Hoechst")
        ch = queries.select_channel_by_name(db_conn, "Hoechst")
        assert ch.name == "Hoechst"

    def test_rename_channel_duplicate(self, db_conn):
        queries.insert_channel(db_conn, "DAPI")
        queries.insert_channel(db_conn, "GFP")
        with pytest.raises(DuplicateError):
            queries.rename_channel(db_conn, "DAPI", "GFP")

    def test_rename_bio_rep(self, db_conn):
        queries.insert_bio_rep(db_conn, "N1")
        queries.rename_bio_rep(db_conn, "N1", "Rep1")
        reps = queries.select_bio_reps(db_conn)
        assert "Rep1" in reps
        assert "N1" not in reps

    def test_rename_fov(self, db_conn):
        cid = queries.insert_condition(db_conn, "control")
        br_id = queries.insert_bio_rep(db_conn, "N1")
        fov_id = queries.insert_fov(db_conn, "FOV_1", condition_id=cid, bio_rep_id=br_id)
        queries.rename_fov(db_conn, fov_id, "FOV_A")
        fovs = queries.select_fovs(db_conn, condition_id=cid)
        names = [f.display_name for f in fovs]
        assert "FOV_A" in names
        assert "FOV_1" not in names


# ---------------------------------------------------------------------------
# Delete cells for FOV
# ---------------------------------------------------------------------------


class TestDeleteCellsForFov:
    def _setup(self, db_conn):
        ch_id = queries.insert_channel(db_conn, "DAPI")
        cond_id = queries.insert_condition(db_conn, "control")
        br_id = queries.insert_bio_rep(db_conn, "N1")
        fov_id = queries.insert_fov(db_conn, "ctrl_N1_FOV_001", condition_id=cond_id, bio_rep_id=br_id)
        seg_id = _make_seg(db_conn, "seg", source_fov_id=fov_id, source_channel="DAPI")
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
        for cid in cell_ids:
            queries.insert_measurements(db_conn, [
                MeasurementRecord(cell_id=cid, channel_id=ch_id,
                                  metric="mean", value=42.0,
                                  segmentation_id=seg_id),
            ])
        return fov_id, cell_ids

    def test_deletes_cells_and_measurements(self, db_conn):
        fov_id, cell_ids = self._setup(db_conn)
        assert queries.count_cells(db_conn) == 3

        deleted = queries.delete_cells_for_fov(db_conn, fov_id)
        assert deleted == 3
        assert queries.count_cells(db_conn) == 0
        rows = queries.select_measurements(db_conn, cell_ids=cell_ids)
        assert len(rows) == 0

    def test_no_cells_returns_zero(self, db_conn):
        cond_id = queries.insert_condition(db_conn, "ctrl")
        br_id = queries.insert_bio_rep(db_conn, "N1")
        fov_id = queries.insert_fov(db_conn, "empty_FOV", condition_id=cond_id, bio_rep_id=br_id)
        assert queries.delete_cells_for_fov(db_conn, fov_id) == 0


# ---------------------------------------------------------------------------
# FOV segmentation summary
# ---------------------------------------------------------------------------


class TestFovSegmentationSummary:
    def test_mixed_segmented_and_unsegmented(self, db_conn):
        queries.insert_channel(db_conn, "DAPI")
        cond_id = queries.insert_condition(db_conn, "ctrl")
        br_id = queries.insert_bio_rep(db_conn, "N1")
        fov1_id = queries.insert_fov(db_conn, "ctrl_N1_FOV_001", condition_id=cond_id, bio_rep_id=br_id)
        fov2_id = queries.insert_fov(db_conn, "ctrl_N1_FOV_002", condition_id=cond_id, bio_rep_id=br_id)
        seg_id = _make_seg(db_conn, "seg", source_fov_id=fov1_id, source_channel="DAPI", model_name="cpsam")

        cells = [
            CellRecord(
                fov_id=fov1_id, segmentation_id=seg_id, label_value=i,
                centroid_x=100, centroid_y=200,
                bbox_x=80, bbox_y=180, bbox_w=40, bbox_h=40,
                area_pixels=1200,
            )
            for i in range(1, 6)
        ]
        queries.insert_cells(db_conn, cells)

        summary = queries.select_fov_segmentation_summary(db_conn)
        assert summary[fov1_id] == (5, "cpsam")
        assert summary[fov2_id] == (0, None)


# ---------------------------------------------------------------------------
# Particle queries
# ---------------------------------------------------------------------------


class TestParticleQueries:
    def _setup(self, db_conn):
        """Create channel, condition, FOV, segmentation, cells, threshold."""
        ch_id = queries.insert_channel(db_conn, "GFP")
        cond_id = queries.insert_condition(db_conn, "control")
        br_id = queries.insert_bio_rep(db_conn, "N1")
        fov_id = queries.insert_fov(db_conn, "ctrl_N1_FOV_001", condition_id=cond_id, bio_rep_id=br_id)
        seg_id = _make_seg(db_conn, "seg", source_fov_id=fov_id, source_channel="GFP", model_name="cpsam")
        cells = [
            CellRecord(
                fov_id=fov_id, segmentation_id=seg_id, label_value=i,
                centroid_x=50, centroid_y=50,
                bbox_x=20, bbox_y=20, bbox_w=60, bbox_h=60,
                area_pixels=800,
            )
            for i in range(1, 3)
        ]
        cell_ids = queries.insert_cells(db_conn, cells)
        thr_id = _make_thresh(db_conn, "thr", source_fov_id=fov_id, source_channel="GFP")
        return fov_id, cell_ids, thr_id, ch_id

    def test_insert_and_select_particles(self, db_conn):
        fov_id, cell_ids, thr_id, _ = self._setup(db_conn)
        particles = [
            ParticleRecord(
                fov_id=fov_id, threshold_id=thr_id, label_value=1,
                centroid_x=30.0, centroid_y=40.0,
                bbox_x=25, bbox_y=35, bbox_w=10, bbox_h=10,
                area_pixels=50.0, perimeter=25.0, circularity=0.8,
            ),
            ParticleRecord(
                fov_id=fov_id, threshold_id=thr_id, label_value=2,
                centroid_x=60.0, centroid_y=60.0,
                bbox_x=55, bbox_y=55, bbox_w=12, bbox_h=12,
                area_pixels=80.0,
            ),
        ]
        queries.insert_particles(db_conn, particles)

        rows = queries.select_particles(db_conn, fov_id=fov_id)
        assert len(rows) == 2
        assert rows[0]["label_value"] == 1
        assert rows[0]["area_pixels"] == 50.0
        assert rows[1]["label_value"] == 2

    def test_select_by_threshold(self, db_conn):
        fov_id, cell_ids, thr_id, ch_id = self._setup(db_conn)
        thr_id2 = _make_thresh(db_conn, "thr_manual", method="manual",
                               source_fov_id=fov_id, source_channel="GFP")
        particles = [
            ParticleRecord(
                fov_id=fov_id, threshold_id=thr_id, label_value=1,
                centroid_x=30.0, centroid_y=40.0,
                bbox_x=25, bbox_y=35, bbox_w=10, bbox_h=10,
                area_pixels=50.0,
            ),
            ParticleRecord(
                fov_id=fov_id, threshold_id=thr_id2, label_value=1,
                centroid_x=31.0, centroid_y=41.0,
                bbox_x=26, bbox_y=36, bbox_w=10, bbox_h=10,
                area_pixels=55.0,
            ),
        ]
        queries.insert_particles(db_conn, particles)

        rows = queries.select_particles(db_conn, threshold_id=thr_id)
        assert len(rows) == 1
        assert rows[0]["threshold_id"] == thr_id

    def test_delete_particles_for_fov(self, db_conn):
        fov_id, cell_ids, thr_id, _ = self._setup(db_conn)
        particles = [
            ParticleRecord(
                fov_id=fov_id, threshold_id=thr_id, label_value=1,
                centroid_x=30.0, centroid_y=40.0,
                bbox_x=25, bbox_y=35, bbox_w=10, bbox_h=10,
                area_pixels=50.0,
            ),
            ParticleRecord(
                fov_id=fov_id, threshold_id=thr_id, label_value=2,
                centroid_x=60.0, centroid_y=60.0,
                bbox_x=55, bbox_y=55, bbox_w=10, bbox_h=10,
                area_pixels=80.0,
            ),
        ]
        queries.insert_particles(db_conn, particles)

        deleted = queries.delete_particles_for_fov(db_conn, fov_id)
        assert deleted == 2
        assert queries.select_particles(db_conn) == []

    def test_delete_particles_for_threshold(self, db_conn):
        fov_id, cell_ids, thr_id, _ = self._setup(db_conn)
        particles = [
            ParticleRecord(
                fov_id=fov_id, threshold_id=thr_id, label_value=1,
                centroid_x=30.0, centroid_y=40.0,
                bbox_x=25, bbox_y=35, bbox_w=10, bbox_h=10,
                area_pixels=50.0,
            ),
        ]
        queries.insert_particles(db_conn, particles)

        deleted = queries.delete_particles_for_threshold(db_conn, thr_id)
        assert deleted == 1
        assert queries.select_particles(db_conn) == []

    def test_empty_insert_is_noop(self, db_conn):
        queries.insert_particles(db_conn, [])
        assert queries.select_particles(db_conn) == []

    def test_select_particles_with_context(self, db_conn):
        fov_id, cell_ids, thr_id, _ = self._setup(db_conn)
        particles = [
            ParticleRecord(
                fov_id=fov_id, threshold_id=thr_id, label_value=1,
                centroid_x=30.0, centroid_y=40.0,
                bbox_x=25, bbox_y=35, bbox_w=10, bbox_h=10,
                area_pixels=50.0,
            ),
        ]
        queries.insert_particles(db_conn, particles)

        rows = queries.select_particles_with_context(db_conn, threshold_id=thr_id)
        assert len(rows) == 1
        assert rows[0]["fov_name"] == "ctrl_N1_FOV_001"
        assert rows[0]["condition_name"] == "control"
        assert rows[0]["bio_rep_name"] == "N1"


# ---------------------------------------------------------------------------
# Delete tags by prefix
# ---------------------------------------------------------------------------


class TestDeleteTagsByPrefix:
    def _setup(self, db_conn):
        queries.insert_channel(db_conn, "GFP")
        cond_id = queries.insert_condition(db_conn, "ctrl")
        br_id = queries.insert_bio_rep(db_conn, "N1")
        fov_id = queries.insert_fov(db_conn, "ctrl_N1_FOV_001", condition_id=cond_id, bio_rep_id=br_id)
        seg_id = _make_seg(db_conn, "seg", source_fov_id=fov_id, source_channel="GFP", model_name="cpsam")
        return fov_id, seg_id

    def test_delete_matching_tags(self, db_conn):
        fov_id, seg_id = self._setup(db_conn)
        cells = [
            CellRecord(
                fov_id=fov_id, segmentation_id=seg_id, label_value=1,
                centroid_x=50, centroid_y=50,
                bbox_x=20, bbox_y=20, bbox_w=60, bbox_h=60,
                area_pixels=800,
            ),
        ]
        cell_ids = queries.insert_cells(db_conn, cells)

        tag1_id = queries.insert_tag(db_conn, "group:GFP:mean:g1")
        tag2_id = queries.insert_tag(db_conn, "group:GFP:mean:g2")
        tag3_id = queries.insert_tag(db_conn, "manual_flag")
        queries.insert_cell_tags(db_conn, cell_ids, tag1_id)
        queries.insert_cell_tags(db_conn, cell_ids, tag3_id)

        deleted = queries.delete_tags_by_prefix(db_conn, "group:GFP:mean:")
        assert deleted == 1

        remaining = queries.select_tags(db_conn)
        assert "manual_flag" in remaining
        assert "group:GFP:mean:g1" not in remaining

    def test_delete_with_cell_ids_scope(self, db_conn):
        fov_id, seg_id = self._setup(db_conn)
        cells = [
            CellRecord(
                fov_id=fov_id, segmentation_id=seg_id, label_value=i,
                centroid_x=50, centroid_y=50,
                bbox_x=20, bbox_y=20, bbox_w=60, bbox_h=60,
                area_pixels=800,
            )
            for i in range(1, 3)
        ]
        cell_ids = queries.insert_cells(db_conn, cells)

        tag_id = queries.insert_tag(db_conn, "group:GFP:mean:g1")
        queries.insert_cell_tags(db_conn, cell_ids, tag_id)

        deleted = queries.delete_tags_by_prefix(
            db_conn, "group:GFP:mean:", cell_ids=[cell_ids[0]]
        )
        assert deleted == 1

        assert "group:GFP:mean:g1" in queries.select_tags(db_conn)

    def test_no_matching_prefix(self, db_conn):
        deleted = queries.delete_tags_by_prefix(db_conn, "nonexistent:")
        assert deleted == 0


# ---------------------------------------------------------------------------
# Experiment summary
# ---------------------------------------------------------------------------


class TestExperimentSummary:
    def test_empty_experiment(self, db_conn):
        """No FOVs returns empty list."""
        rows = queries.select_experiment_summary(db_conn)
        assert rows == []

    def test_cells_no_measurements(self, db_conn):
        """FOV with cells but no measurements."""
        queries.insert_channel(db_conn, "DAPI")
        cond_id = queries.insert_condition(db_conn, "ctrl")
        br_id = queries.insert_bio_rep(db_conn, "N1")
        fov_id = queries.insert_fov(
            db_conn, "ctrl_N1_FOV_001", condition_id=cond_id, bio_rep_id=br_id,
            width=64, height=64,
        )
        seg_id = _make_seg(db_conn, "seg", source_fov_id=fov_id, source_channel="DAPI", model_name="cyto3")
        cells = [
            CellRecord(
                fov_id=fov_id, segmentation_id=seg_id, label_value=i,
                centroid_x=10.0, centroid_y=10.0,
                bbox_x=0, bbox_y=0, bbox_w=10, bbox_h=10,
                area_pixels=100.0,
            )
            for i in range(1, 4)
        ]
        queries.insert_cells(db_conn, cells)

        rows = queries.select_experiment_summary(db_conn)
        assert len(rows) == 1
        r = rows[0]
        assert r["condition_name"] == "ctrl"
        assert r["fov_name"] == "ctrl_N1_FOV_001"
        assert r["cells"] == 3
        assert r["seg_model"] == "cyto3"
        assert r["measured_channels"] == ""
        assert r["masked_channels"] == ""
        assert r["particle_channels"] == ""
        assert r["particles"] == 0

    def test_full_summary(self, db_conn):
        """FOV with cells, measurements, and particles."""
        ch_id = queries.insert_channel(db_conn, "GFP")
        cond_id = queries.insert_condition(db_conn, "treated")
        br_id = queries.insert_bio_rep(db_conn, "N1")
        fov_id = queries.insert_fov(
            db_conn, "treated_N1_FOV_001", condition_id=cond_id, bio_rep_id=br_id,
            width=64, height=64,
        )
        seg_id = _make_seg(db_conn, "seg", source_fov_id=fov_id, source_channel="GFP", model_name="cyto3")

        cells = [
            CellRecord(
                fov_id=fov_id, segmentation_id=seg_id, label_value=i,
                centroid_x=10.0, centroid_y=10.0,
                bbox_x=0, bbox_y=0, bbox_w=10, bbox_h=10,
                area_pixels=100.0,
            )
            for i in range(1, 3)
        ]
        cell_ids = queries.insert_cells(db_conn, cells)

        measurements = [
            MeasurementRecord(
                cell_id=cid, channel_id=ch_id,
                metric="mean_intensity", value=50.0,
                segmentation_id=seg_id,
            )
            for cid in cell_ids
        ]
        measurements += [
            MeasurementRecord(
                cell_id=cid, channel_id=ch_id,
                metric="mean_intensity", value=30.0,
                scope="mask_inside", segmentation_id=seg_id,
            )
            for cid in cell_ids
        ]
        measurements.append(
            MeasurementRecord(
                cell_id=cell_ids[0], channel_id=ch_id,
                metric="particle_count", value=2.0,
                segmentation_id=seg_id,
            )
        )
        queries.insert_measurements(db_conn, measurements)

        thr_id = _make_thresh(db_conn, "thr", source_fov_id=fov_id, source_channel="GFP")
        particles = [
            ParticleRecord(
                fov_id=fov_id, threshold_id=thr_id, label_value=j,
                centroid_x=5.0, centroid_y=5.0,
                bbox_x=0, bbox_y=0, bbox_w=5, bbox_h=5,
                area_pixels=20.0, mean_intensity=80.0,
                max_intensity=120.0, integrated_intensity=1600.0,
            )
            for j in range(1, 4)
        ]
        queries.insert_particles(db_conn, particles)

        rows = queries.select_experiment_summary(db_conn)
        assert len(rows) == 1
        r = rows[0]
        assert r["cells"] == 2
        assert "GFP" in r["measured_channels"]
        assert "GFP" in r["masked_channels"]
        assert "GFP" in r["particle_channels"]
        assert r["particles"] == 3


# ---------------------------------------------------------------------------
# Display name generation
# ---------------------------------------------------------------------------


class TestDisplayNameGeneration:
    def test_basic_generation(self, db_conn):
        cond_id = queries.insert_condition(db_conn, "HS")
        name = queries.generate_display_name(db_conn, "HS", "N1")
        assert name == "HS_N1_FOV_001"

    def test_sequential_names(self, db_conn):
        cond_id = queries.insert_condition(db_conn, "HS")
        br_id = queries.insert_bio_rep(db_conn, "N1")

        name1 = queries.generate_display_name(db_conn, "HS", "N1")
        queries.insert_fov(db_conn, name1, condition_id=cond_id, bio_rep_id=br_id)

        name2 = queries.generate_display_name(db_conn, "HS", "N1")
        assert name2 == "HS_N1_FOV_002"


# ---------------------------------------------------------------------------
# FOV status cache
# ---------------------------------------------------------------------------


class TestFovStatusCache:
    def test_upsert_and_select(self, db_conn):
        import json as _json

        cond_id = queries.insert_condition(db_conn, "ctrl")
        br_id = queries.insert_bio_rep(db_conn, "N1")
        fov_id = queries.insert_fov(db_conn, "ctrl_N1_FOV_001", condition_id=cond_id, bio_rep_id=br_id)

        status = {
            "cell_count": 10,
            "seg_model": "cpsam",
            "measured_channels": "GFP,DAPI",
            "masked_channels": "GFP",
            "particle_channels": "GFP",
            "particle_count": 42,
        }
        queries.upsert_fov_status_cache(db_conn, fov_id, _json.dumps(status))

        rows = queries.select_fov_status_cache(db_conn)
        assert len(rows) == 1
        r = rows[0]
        assert r["fov_id"] == fov_id
        assert r["status"]["cell_count"] == 10
        assert r["status"]["seg_model"] == "cpsam"
        assert r["status"]["particle_count"] == 42


# ---------------------------------------------------------------------------
# FOV tags
# ---------------------------------------------------------------------------


class TestFovTags:
    def test_add_and_select_fov_tags(self, db_conn):
        cond_id = queries.insert_condition(db_conn, "ctrl")
        br_id = queries.insert_bio_rep(db_conn, "N1")
        fov_id = queries.insert_fov(db_conn, "ctrl_N1_FOV_001", condition_id=cond_id, bio_rep_id=br_id)
        tag_id = queries.insert_tag(db_conn, "batch1")

        queries.insert_fov_tag(db_conn, fov_id, tag_id)
        tags = queries.select_fov_tags(db_conn, fov_id)
        assert len(tags) == 1
        assert tags[0]["name"] == "batch1"

    def test_delete_fov_tag(self, db_conn):
        cond_id = queries.insert_condition(db_conn, "ctrl")
        br_id = queries.insert_bio_rep(db_conn, "N1")
        fov_id = queries.insert_fov(db_conn, "ctrl_N1_FOV_001", condition_id=cond_id, bio_rep_id=br_id)
        tag_id = queries.insert_tag(db_conn, "batch1")

        queries.insert_fov_tag(db_conn, fov_id, tag_id)
        queries.delete_fov_tag(db_conn, fov_id, tag_id)
        tags = queries.select_fov_tags(db_conn, fov_id)
        assert len(tags) == 0

    def test_select_fovs_by_tag(self, db_conn):
        cond_id = queries.insert_condition(db_conn, "ctrl")
        br_id = queries.insert_bio_rep(db_conn, "N1")
        fov1 = queries.insert_fov(db_conn, "FOV_1", condition_id=cond_id, bio_rep_id=br_id)
        fov2 = queries.insert_fov(db_conn, "FOV_2", condition_id=cond_id, bio_rep_id=br_id)
        tag_id = queries.insert_tag(db_conn, "batch1")

        queries.insert_fov_tag(db_conn, fov1, tag_id)
        fov_ids = queries.select_fovs_by_tag(db_conn, "batch1")
        assert fov_ids == [fov1]
