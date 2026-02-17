"""Abstract segmentation interface and parameter definitions."""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass(frozen=True)
class SegmentationParams:
    """Parameters for a segmentation run.

    Attributes:
        channel: Which channel to segment.
        model_name: Cellpose model name (e.g., "cpsam", "cyto3", "nuclei").
        diameter: Expected cell diameter in pixels. None = auto-detect.
        flow_threshold: Cellpose flow error threshold (0-3).
        cellprob_threshold: Cell probability threshold (-6 to 6).
        gpu: Whether to use GPU for segmentation.
        min_size: Minimum cell area in pixels.
        normalize: Whether to normalize the image before segmentation.
        channels_cellpose: Cellpose channel config [cyto, nucleus]. None = [0, 0] (grayscale).
    """

    channel: str
    model_name: str = "cpsam"
    diameter: float | None = None
    flow_threshold: float = 0.4
    cellprob_threshold: float = 0.0
    gpu: bool = True
    min_size: int = 15
    normalize: bool = True
    channels_cellpose: list[int] | None = None

    def __post_init__(self) -> None:
        """Validate parameters."""
        if not self.channel:
            raise ValueError("channel must not be empty")
        if not self.model_name:
            raise ValueError("model_name must not be empty")
        if self.min_size < 0:
            raise ValueError(f"min_size must be >= 0, got {self.min_size}")
        if not (0 <= self.flow_threshold <= 3):
            raise ValueError(
                f"flow_threshold must be between 0 and 3, got {self.flow_threshold}"
            )
        if self.diameter is not None and self.diameter <= 0:
            raise ValueError(f"diameter must be > 0 or None, got {self.diameter}")

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict for storing in segmentation_runs.parameters."""
        return {
            "channel": self.channel,
            "model_name": self.model_name,
            "diameter": self.diameter,
            "flow_threshold": self.flow_threshold,
            "cellprob_threshold": self.cellprob_threshold,
            "gpu": self.gpu,
            "min_size": self.min_size,
            "normalize": self.normalize,
            "channels_cellpose": self.channels_cellpose,
        }


@dataclass(frozen=True)
class SegmentationResult:
    """Result of a segmentation run.

    Attributes:
        run_id: Segmentation run ID in the database.
        cell_count: Total number of cells detected across all regions.
        regions_processed: Number of regions that were segmented.
        warnings: List of warning messages (e.g., regions with 0 cells).
        elapsed_seconds: Wall-clock time for the segmentation run.
    """

    run_id: int
    cell_count: int
    regions_processed: int
    warnings: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0


class BaseSegmenter(ABC):
    """Abstract interface for segmentation backends.

    Concrete implementations (e.g., CellposeAdapter) must implement
    ``segment()`` and ``segment_batch()``.
    """

    @abstractmethod
    def segment(self, image: np.ndarray, params: SegmentationParams) -> np.ndarray:
        """Run segmentation on a 2D image.

        Args:
            image: 2D array (Y, X) of the channel to segment.
            params: Segmentation parameters.

        Returns:
            Label image (Y, X) as int32 where pixel value = cell ID, 0 = background.
        """

    @abstractmethod
    def segment_batch(
        self, images: list[np.ndarray], params: SegmentationParams
    ) -> list[np.ndarray]:
        """Run segmentation on multiple images (for GPU batching).

        Args:
            images: List of 2D arrays (Y, X).
            params: Segmentation parameters.

        Returns:
            List of label images (Y, X) as int32.
        """
