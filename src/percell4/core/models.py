"""Frozen dataclass domain models for PerCell 4.

Every model is ``frozen=True, slots=True, kw_only=True`` so instances are
immutable value objects suitable for use as dict keys and in sets.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from percell4.core.constants import FovStatus
from percell4.core.db_types import (
    BioRepId,
    CellIdentityId,
    ChannelId,
    ConditionId,
    ExperimentId,
    FovId,
    IntensityGroupId,
    PipelineRunId,
    RoiId,
    RoiTypeDefinitionId,
    SegmentationSetId,
    ThresholdMaskId,
    TimepointId,
)

# ---------------------------------------------------------------------------
# FOV
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class FovInfo:
    """Immutable snapshot of a field-of-view record."""

    id: FovId
    experiment_id: ExperimentId
    condition_id: ConditionId | None = None
    bio_rep_id: BioRepId | None = None
    parent_fov_id: FovId | None = None
    derivation_op: str | None = None
    derivation_params: str | None = None
    status: FovStatus
    auto_name: str | None = None
    display_name: str | None = None
    zarr_path: str | None = None
    timepoint_id: TimepointId | None = None
    pixel_size_um: float | None = None
    pipeline_run_id: PipelineRunId | None = None
    lineage_depth: int = 0
    lineage_path: str | None = None
    channel_metadata: str | None = None


# ---------------------------------------------------------------------------
# ROI
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class RoiRecord:
    """Immutable snapshot of a region-of-interest (cell, particle, etc.)."""

    id: RoiId
    fov_id: FovId
    roi_type_id: RoiTypeDefinitionId
    cell_identity_id: CellIdentityId | None = None
    parent_roi_id: RoiId | None = None
    label_id: int
    bbox_y: int
    bbox_x: int
    bbox_h: int
    bbox_w: int
    area_px: int


# ---------------------------------------------------------------------------
# Cell Identity
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class CellIdentity:
    """Links an ROI across derived FOVs back to a single biological entity."""

    id: CellIdentityId
    origin_fov_id: FovId
    roi_type_id: RoiTypeDefinitionId


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class MeasurementRecord:
    """A single scalar measurement for one ROI x channel x metric x scope.

    ``value`` is nullable: NaN measurements are stored as NULL in SQLite
    because SQLite REAL columns do not round-trip IEEE NaN.
    """

    roi_id: RoiId
    channel_id: ChannelId
    metric: str
    scope: str
    value: float | None
    pipeline_run_id: PipelineRunId


# ---------------------------------------------------------------------------
# Segmentation Set
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class SegmentationSet:
    """A named segmentation configuration applied to one or more FOVs."""

    id: SegmentationSetId
    experiment_id: ExperimentId
    produces_roi_type_id: RoiTypeDefinitionId
    seg_type: str
    op_config_name: str | None = None
    source_channel: str | None = None
    model_name: str | None = None
    parameters: dict | None = None
    fov_count: int
    total_roi_count: int


# ---------------------------------------------------------------------------
# Channel
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class ChannelInfo:
    """Immutable snapshot of a channel record."""

    id: ChannelId
    experiment_id: ExperimentId
    name: str
    role: str | None = None
    color: str | None = None
    display_order: int


# ---------------------------------------------------------------------------
# Condition
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class ConditionInfo:
    """Immutable snapshot of an experimental condition."""

    id: ConditionId
    experiment_id: ExperimentId
    name: str


# ---------------------------------------------------------------------------
# Biological Replicate
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class BioRepInfo:
    """Immutable snapshot of a biological replicate."""

    id: BioRepId
    experiment_id: ExperimentId
    condition_id: ConditionId
    name: str


# ---------------------------------------------------------------------------
# Timepoint
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class TimepointInfo:
    """Immutable snapshot of a timepoint record."""

    id: TimepointId
    experiment_id: ExperimentId
    name: str
    time_seconds: float | None = None
    display_order: int


# ---------------------------------------------------------------------------
# ROI Type Definition
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class RoiTypeDefinition:
    """Defines a type of ROI (cell, particle, sub-cellular structure, etc.)."""

    id: RoiTypeDefinitionId
    experiment_id: ExperimentId
    name: str
    parent_type_id: RoiTypeDefinitionId | None = None


# ---------------------------------------------------------------------------
# Pipeline Run
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class PipelineRun:
    """Immutable record of a pipeline execution step."""

    id: PipelineRunId
    operation_name: str
    config_snapshot: dict | None = None
    status: str
    started_at: str
    completed_at: str | None = None
    error_message: str | None = None


# ---------------------------------------------------------------------------
# Internal helper: measurement work item
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class MeasurementNeeded:
    """Describes a pending measurement job emitted by config-change logic."""

    fov_id: FovId
    roi_type_id: RoiTypeDefinitionId
    channel_ids: list[ChannelId]
    reason: Literal["new_assignment", "reassignment"]


# ---------------------------------------------------------------------------
# Threshold Mask
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class ThresholdMaskInfo:
    """Immutable snapshot of a threshold mask record."""

    id: ThresholdMaskId
    fov_id: FovId
    source_channel: str
    grouping_channel: str | None = None
    method: str
    threshold_value: float
    zarr_path: str | None = None
    status: str
