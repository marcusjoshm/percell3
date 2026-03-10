"""Tests for percell4.core.models — frozen domain dataclasses."""

from __future__ import annotations

import dataclasses

import pytest

from percell4.core.constants import FovStatus
from percell4.core.db_types import new_uuid
from percell4.core.models import (
    BioRepInfo,
    CellIdentity,
    ChannelInfo,
    ConditionInfo,
    FovInfo,
    MeasurementNeeded,
    MeasurementRecord,
    PipelineRun,
    RoiRecord,
    RoiTypeDefinition,
    SegmentationSet,
    ThresholdMaskInfo,
    TimepointInfo,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uid() -> bytes:
    return new_uuid()


# ---------------------------------------------------------------------------
# FovInfo
# ---------------------------------------------------------------------------


class TestFovInfo:
    def test_creation(self) -> None:
        eid = _uid()
        fid = _uid()
        fov = FovInfo(
            id=fid,
            experiment_id=eid,
            status=FovStatus.imported,
            display_name="FOV-001",
        )
        assert fov.id == fid
        assert fov.experiment_id == eid
        assert fov.status == FovStatus.imported
        assert fov.display_name == "FOV-001"

    def test_optional_fields_default_none(self) -> None:
        fov = FovInfo(
            id=_uid(),
            experiment_id=_uid(),
            status=FovStatus.pending,
            display_name="test",
        )
        assert fov.condition_id is None
        assert fov.bio_rep_id is None
        assert fov.parent_fov_id is None
        assert fov.derivation_op is None
        assert fov.auto_name is None
        assert fov.zarr_path is None
        assert fov.timepoint_id is None

    def test_frozen(self) -> None:
        fov = FovInfo(
            id=_uid(),
            experiment_id=_uid(),
            status=FovStatus.pending,
            display_name="test",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            fov.display_name = "mutated"  # type: ignore[misc]

    def test_kw_only(self) -> None:
        with pytest.raises(TypeError):
            FovInfo(  # type: ignore[misc]
                _uid(),
                _uid(),
                None,
                None,
                None,
                None,
                FovStatus.pending,
                None,
                None,
                None,
                "test",
            )


# ---------------------------------------------------------------------------
# RoiRecord
# ---------------------------------------------------------------------------


class TestRoiRecord:
    def test_creation(self) -> None:
        roi = RoiRecord(
            id=_uid(),
            fov_id=_uid(),
            roi_type_id=_uid(),
            label_id=1,
            bbox_y=10,
            bbox_x=20,
            bbox_h=50,
            bbox_w=60,
            area_px=3000,
        )
        assert roi.label_id == 1
        assert roi.area_px == 3000

    def test_frozen(self) -> None:
        roi = RoiRecord(
            id=_uid(),
            fov_id=_uid(),
            roi_type_id=_uid(),
            label_id=1,
            bbox_y=0,
            bbox_x=0,
            bbox_h=10,
            bbox_w=10,
            area_px=100,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            roi.label_id = 99  # type: ignore[misc]

    def test_optional_fields(self) -> None:
        roi = RoiRecord(
            id=_uid(),
            fov_id=_uid(),
            roi_type_id=_uid(),
            label_id=1,
            bbox_y=0,
            bbox_x=0,
            bbox_h=10,
            bbox_w=10,
            area_px=100,
        )
        assert roi.cell_identity_id is None
        assert roi.parent_roi_id is None


# ---------------------------------------------------------------------------
# CellIdentity
# ---------------------------------------------------------------------------


class TestCellIdentity:
    def test_creation(self) -> None:
        cid = _uid()
        ci = CellIdentity(id=cid, origin_fov_id=_uid(), roi_type_id=_uid())
        assert ci.id == cid

    def test_frozen(self) -> None:
        ci = CellIdentity(id=_uid(), origin_fov_id=_uid(), roi_type_id=_uid())
        with pytest.raises(dataclasses.FrozenInstanceError):
            ci.id = _uid()  # type: ignore[misc]


# ---------------------------------------------------------------------------
# MeasurementRecord
# ---------------------------------------------------------------------------


class TestMeasurementRecord:
    def test_creation(self) -> None:
        m = MeasurementRecord(
            roi_id=_uid(),
            channel_id=_uid(),
            metric="mean",
            scope="whole_roi",
            value=42.5,
            pipeline_run_id=_uid(),
        )
        assert m.value == 42.5
        assert m.metric == "mean"

    def test_frozen(self) -> None:
        m = MeasurementRecord(
            roi_id=_uid(),
            channel_id=_uid(),
            metric="mean",
            scope="whole_roi",
            value=1.0,
            pipeline_run_id=_uid(),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            m.value = 99.9  # type: ignore[misc]


# ---------------------------------------------------------------------------
# SegmentationSet
# ---------------------------------------------------------------------------


class TestSegmentationSet:
    def test_creation(self) -> None:
        ss = SegmentationSet(
            id=_uid(),
            experiment_id=_uid(),
            produces_roi_type_id=_uid(),
            seg_type="cellpose",
            fov_count=5,
            total_roi_count=120,
        )
        assert ss.seg_type == "cellpose"
        assert ss.fov_count == 5

    def test_optional_fields(self) -> None:
        ss = SegmentationSet(
            id=_uid(),
            experiment_id=_uid(),
            produces_roi_type_id=_uid(),
            seg_type="manual",
            fov_count=1,
            total_roi_count=10,
        )
        assert ss.op_config_name is None
        assert ss.source_channel is None
        assert ss.model_name is None
        assert ss.parameters is None

    def test_frozen(self) -> None:
        ss = SegmentationSet(
            id=_uid(),
            experiment_id=_uid(),
            produces_roi_type_id=_uid(),
            seg_type="cellpose",
            fov_count=1,
            total_roi_count=10,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            ss.seg_type = "manual"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ChannelInfo
# ---------------------------------------------------------------------------


class TestChannelInfo:
    def test_creation(self) -> None:
        ch = ChannelInfo(
            id=_uid(),
            experiment_id=_uid(),
            name="GFP",
            display_order=0,
        )
        assert ch.name == "GFP"
        assert ch.display_order == 0

    def test_optional_fields(self) -> None:
        ch = ChannelInfo(
            id=_uid(),
            experiment_id=_uid(),
            name="DAPI",
            display_order=1,
        )
        assert ch.role is None
        assert ch.color is None

    def test_frozen(self) -> None:
        ch = ChannelInfo(
            id=_uid(),
            experiment_id=_uid(),
            name="GFP",
            display_order=0,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            ch.name = "RFP"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ConditionInfo
# ---------------------------------------------------------------------------


class TestConditionInfo:
    def test_creation(self) -> None:
        c = ConditionInfo(id=_uid(), experiment_id=_uid(), name="control")
        assert c.name == "control"

    def test_frozen(self) -> None:
        c = ConditionInfo(id=_uid(), experiment_id=_uid(), name="control")
        with pytest.raises(dataclasses.FrozenInstanceError):
            c.name = "treated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# BioRepInfo
# ---------------------------------------------------------------------------


class TestBioRepInfo:
    def test_creation(self) -> None:
        br = BioRepInfo(
            id=_uid(),
            experiment_id=_uid(),
            condition_id=_uid(),
            name="rep1",
        )
        assert br.name == "rep1"

    def test_frozen(self) -> None:
        br = BioRepInfo(
            id=_uid(),
            experiment_id=_uid(),
            condition_id=_uid(),
            name="rep1",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            br.name = "rep2"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TimepointInfo
# ---------------------------------------------------------------------------


class TestTimepointInfo:
    def test_creation(self) -> None:
        tp = TimepointInfo(
            id=_uid(),
            experiment_id=_uid(),
            name="t0",
            display_order=0,
        )
        assert tp.name == "t0"
        assert tp.time_seconds is None

    def test_with_time_seconds(self) -> None:
        tp = TimepointInfo(
            id=_uid(),
            experiment_id=_uid(),
            name="t30",
            time_seconds=30.0,
            display_order=1,
        )
        assert tp.time_seconds == 30.0

    def test_frozen(self) -> None:
        tp = TimepointInfo(
            id=_uid(),
            experiment_id=_uid(),
            name="t0",
            display_order=0,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            tp.name = "t1"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# RoiTypeDefinition
# ---------------------------------------------------------------------------


class TestRoiTypeDefinition:
    def test_creation(self) -> None:
        rtd = RoiTypeDefinition(
            id=_uid(),
            experiment_id=_uid(),
            name="cell",
        )
        assert rtd.name == "cell"
        assert rtd.parent_type_id is None

    def test_with_parent(self) -> None:
        parent_id = _uid()
        rtd = RoiTypeDefinition(
            id=_uid(),
            experiment_id=_uid(),
            name="particle",
            parent_type_id=parent_id,
        )
        assert rtd.parent_type_id == parent_id

    def test_frozen(self) -> None:
        rtd = RoiTypeDefinition(id=_uid(), experiment_id=_uid(), name="cell")
        with pytest.raises(dataclasses.FrozenInstanceError):
            rtd.name = "nucleus"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# PipelineRun
# ---------------------------------------------------------------------------


class TestPipelineRun:
    def test_creation(self) -> None:
        pr = PipelineRun(
            id=_uid(),
            operation_name="segment",
            status="running",
            started_at="2026-03-10T10:00:00",
        )
        assert pr.operation_name == "segment"
        assert pr.config_snapshot is None
        assert pr.completed_at is None
        assert pr.error_message is None

    def test_frozen(self) -> None:
        pr = PipelineRun(
            id=_uid(),
            operation_name="segment",
            status="running",
            started_at="2026-03-10T10:00:00",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            pr.status = "done"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# MeasurementNeeded
# ---------------------------------------------------------------------------


class TestMeasurementNeeded:
    def test_creation_new_assignment(self) -> None:
        mn = MeasurementNeeded(
            fov_id=_uid(),
            roi_type_id=_uid(),
            channel_ids=[_uid(), _uid()],
            reason="new_assignment",
        )
        assert mn.reason == "new_assignment"
        assert len(mn.channel_ids) == 2

    def test_creation_reassignment(self) -> None:
        mn = MeasurementNeeded(
            fov_id=_uid(),
            roi_type_id=_uid(),
            channel_ids=[_uid()],
            reason="reassignment",
        )
        assert mn.reason == "reassignment"

    def test_frozen(self) -> None:
        mn = MeasurementNeeded(
            fov_id=_uid(),
            roi_type_id=_uid(),
            channel_ids=[],
            reason="new_assignment",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            mn.reason = "reassignment"  # type: ignore[misc]

    def test_kw_only(self) -> None:
        with pytest.raises(TypeError):
            MeasurementNeeded(  # type: ignore[misc]
                _uid(),
                _uid(),
                [],
                "new_assignment",
            )


# ---------------------------------------------------------------------------
# ThresholdMaskInfo
# ---------------------------------------------------------------------------


class TestThresholdMaskInfo:
    def test_creation(self) -> None:
        tm = ThresholdMaskInfo(
            id=_uid(),
            fov_id=_uid(),
            source_channel="GFP",
            method="otsu",
            threshold_value=128.5,
            status="active",
        )
        assert tm.source_channel == "GFP"
        assert tm.threshold_value == 128.5
        assert tm.grouping_channel is None
        assert tm.zarr_path is None

    def test_frozen(self) -> None:
        tm = ThresholdMaskInfo(
            id=_uid(),
            fov_id=_uid(),
            source_channel="GFP",
            method="otsu",
            threshold_value=100.0,
            status="active",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            tm.status = "deleted"  # type: ignore[misc]
