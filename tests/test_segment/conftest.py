"""Shared fixtures for segmentation module tests."""

from __future__ import annotations

import numpy as np
import pytest

from percell3.segment.base_segmenter import BaseSegmenter, SegmentationParams


class MockSegmenter(BaseSegmenter):
    """A mock segmenter that returns pre-defined labels for testing."""

    def __init__(self, labels: np.ndarray | None = None) -> None:
        self._labels = labels

    def segment(self, image: np.ndarray, params: SegmentationParams) -> np.ndarray:
        """Return pre-defined labels or two synthetic cells."""
        if self._labels is not None:
            return self._labels.astype(np.int32)
        # Default: create 2 cells in the image
        labels = np.zeros(image.shape[:2], dtype=np.int32)
        h, w = labels.shape
        # Cell 1: top-left quadrant
        labels[h // 8 : h // 4, w // 8 : w // 4] = 1
        # Cell 2: bottom-right quadrant
        labels[h * 3 // 4 : h * 7 // 8, w * 3 // 4 : w * 7 // 8] = 2
        return labels

    def segment_batch(
        self, images: list[np.ndarray], params: SegmentationParams
    ) -> list[np.ndarray]:
        return [self.segment(img, params) for img in images]


class EmptySegmenter(BaseSegmenter):
    """A mock segmenter that always returns all-zero labels (no cells)."""

    def segment(self, image: np.ndarray, params: SegmentationParams) -> np.ndarray:
        return np.zeros(image.shape[:2], dtype=np.int32)

    def segment_batch(
        self, images: list[np.ndarray], params: SegmentationParams
    ) -> list[np.ndarray]:
        return [self.segment(img, params) for img in images]


@pytest.fixture
def mock_segmenter() -> MockSegmenter:
    """A segmenter that returns 2 synthetic cells."""
    return MockSegmenter()


@pytest.fixture
def empty_segmenter() -> EmptySegmenter:
    """A segmenter that returns 0 cells."""
    return EmptySegmenter()
