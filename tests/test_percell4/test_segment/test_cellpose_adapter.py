"""Tests for percell4.segment.cellpose_adapter — MockSegmenter."""

from __future__ import annotations

import numpy as np

from percell4.segment.cellpose_adapter import MockSegmenter


class TestMockSegmenter:
    """Tests for the MockSegmenter test double."""

    def test_produces_labels_from_synthetic_image(self) -> None:
        """MockSegmenter produces non-zero labels from a bright-on-dark image."""
        # Create a synthetic image with two bright spots on dark background
        image = np.zeros((100, 100), dtype=np.uint16)
        image[20:40, 20:40] = 500   # bright square 1
        image[60:80, 60:80] = 600   # bright square 2

        segmenter = MockSegmenter()
        labels = segmenter.segment(image)

        # Should produce labels
        assert labels.dtype == np.int32
        assert labels.shape == (100, 100)

        # Background should be 0
        assert labels[0, 0] == 0

        # Bright regions should be labeled
        assert labels[30, 30] > 0
        assert labels[70, 70] > 0

        # Two separate objects
        unique_labels = set(np.unique(labels)) - {0}
        assert len(unique_labels) == 2

    def test_uniform_image_returns_no_labels_or_single(self) -> None:
        """Uniform image has no bright regions above mean threshold."""
        image = np.ones((50, 50), dtype=np.uint16) * 100
        segmenter = MockSegmenter()
        labels = segmenter.segment(image)

        # Uniform image: nothing above mean, so no labels
        assert labels.dtype == np.int32
        assert labels.max() == 0

    def test_accepts_kwargs_silently(self) -> None:
        """Extra kwargs are ignored for API compatibility."""
        image = np.zeros((50, 50), dtype=np.uint16)
        image[10:20, 10:20] = 300
        segmenter = MockSegmenter()
        labels = segmenter.segment(
            image, model_name="cyto3", diameter=30.0, gpu=False
        )
        assert labels.dtype == np.int32
