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
    name: str
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
class MeasurementRecord:
    """A single measurement value for one cell on one channel."""

    cell_id: int
    channel_id: int
    metric: str
    value: float
