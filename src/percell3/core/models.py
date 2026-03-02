"""Data models for the PerCell 3 core module."""

from __future__ import annotations

from dataclasses import dataclass, field

@dataclass(frozen=True)
class ChannelConfig:
    """Configuration for an imaging channel."""

    id: int
    name: str
    role: str | None = None
    excitation_nm: float | None = None
    emission_nm: float | None = None
    color: str | None = None
    is_segmentation: bool = False
    display_order: int = 0


@dataclass(frozen=True)
class FovInfo:
    """Metadata for a field of view (FOV)."""

    id: int
    display_name: str
    condition: str
    bio_rep: str = "N1"
    timepoint: str | None = None
    width: int | None = None
    height: int | None = None
    pixel_size_um: float | None = None
    source_file: str | None = None


@dataclass(frozen=True)
class CellRecord:
    """A segmented cell's spatial properties (no id — assigned by SQLite on insert)."""

    fov_id: int
    segmentation_id: int
    label_value: int
    centroid_x: float
    centroid_y: float
    bbox_x: int
    bbox_y: int
    bbox_w: int
    bbox_h: int
    area_pixels: float
    area_um2: float | None = None
    perimeter: float | None = None
    circularity: float | None = None


@dataclass(frozen=True)
class SegmentationInfo:
    """Metadata for a global segmentation entity."""

    id: int
    name: str
    seg_type: str  # 'whole_field' | 'cellular'
    source_fov_id: int | None
    source_channel: str | None
    model_name: str
    parameters: dict | None
    width: int
    height: int
    cell_count: int
    created_at: str


@dataclass(frozen=True)
class ThresholdInfo:
    """Metadata for a global threshold entity."""

    id: int
    name: str
    source_fov_id: int | None
    source_channel: str | None
    grouping_channel: str | None
    method: str
    parameters: dict | None
    threshold_value: float | None
    width: int
    height: int
    created_at: str


@dataclass(frozen=True)
class DeleteImpact:
    """Summary of what will be deleted when a layer is removed."""

    cells: int = 0
    measurements: int = 0
    particles: int = 0
    config_entries: int = 0
    affected_fovs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AnalysisConfig:
    """Metadata for an experiment's analysis configuration."""

    id: int
    experiment_id: int
    created_at: str


@dataclass(frozen=True)
class FovConfigEntry:
    """A single row in the config matrix: one FOV-threshold combination."""

    id: int
    config_id: int
    fov_id: int
    segmentation_id: int
    threshold_id: int | None
    scopes: list[str] = field(default_factory=lambda: ["whole_cell"])


@dataclass(frozen=True)
class MeasurementRecord:
    """A single measurement value for one cell on one channel."""

    cell_id: int
    channel_id: int
    metric: str
    value: float
    scope: str = "whole_cell"
    segmentation_id: int | None = None
    threshold_id: int | None = None
    measured_at: str | None = None


@dataclass(frozen=True)
class ParticleRecord:
    """A single particle detected within a threshold mask on a FOV."""

    fov_id: int
    threshold_id: int
    label_value: int
    centroid_x: float
    centroid_y: float
    bbox_x: int
    bbox_y: int
    bbox_w: int
    bbox_h: int
    area_pixels: float
    area_um2: float | None = None
    perimeter: float | None = None
    circularity: float | None = None
    eccentricity: float | None = None
    solidity: float | None = None
    major_axis_length: float | None = None
    minor_axis_length: float | None = None
    mean_intensity: float | None = None
    max_intensity: float | None = None
    integrated_intensity: float | None = None
