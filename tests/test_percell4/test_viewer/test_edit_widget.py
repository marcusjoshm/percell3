"""Tests for edit widget logic (no Qt required).

Tests the pure numpy helper functions that back the EditWidget:
    - rasterize_polygon: polygon -> label assignment
    - delete_label_from_array: label erasure
"""

from __future__ import annotations

import numpy as np
import pytest

from percell4.viewer.edit_widget import (
    delete_label_from_array,
    rasterize_polygon,
)


# ---------------------------------------------------------------------------
# rasterize_polygon
# ---------------------------------------------------------------------------


class TestRasterizePolygon:
    """Tests for rasterize_polygon()."""

    def test_creates_new_label_from_triangle(self):
        """A triangle polygon should fill pixels with a new label ID."""
        labels = np.zeros((20, 20), dtype=np.int32)

        # Triangle vertices
        rows = np.array([5, 15, 10], dtype=float)
        cols = np.array([5, 5, 15], dtype=float)

        new_id = rasterize_polygon(labels, rows, cols)

        assert new_id == 1  # max(0) + 1
        assert (labels == 1).any()
        # Background pixels should remain 0
        assert labels[0, 0] == 0

    def test_assigns_next_label_id(self):
        """New label should be max(existing) + 1."""
        labels = np.zeros((20, 20), dtype=np.int32)
        labels[0:5, 0:5] = 3  # existing label
        labels[10:15, 10:15] = 7  # existing label

        rows = np.array([6, 9, 6], dtype=float)
        cols = np.array([6, 6, 9], dtype=float)

        new_id = rasterize_polygon(labels, rows, cols)
        assert new_id == 8  # max(7) + 1

    def test_custom_label_id(self):
        """Explicit new_label parameter should be used."""
        labels = np.zeros((20, 20), dtype=np.int32)

        rows = np.array([2, 8, 5], dtype=float)
        cols = np.array([2, 2, 8], dtype=float)

        new_id = rasterize_polygon(labels, rows, cols, new_label=42)
        assert new_id == 42
        assert (labels == 42).any()

    def test_rectangle_polygon(self):
        """A rectangle polygon should fill the expected rectangular region."""
        labels = np.zeros((30, 30), dtype=np.int32)

        # Rectangle: (5,5) -> (5,15) -> (15,15) -> (15,5)
        rows = np.array([5, 5, 15, 15], dtype=float)
        cols = np.array([5, 15, 15, 5], dtype=float)

        new_id = rasterize_polygon(labels, rows, cols)
        assert new_id == 1

        # Center should be filled
        assert labels[10, 10] == 1
        # Corner outside should be empty
        assert labels[0, 0] == 0

    def test_out_of_bounds_polygon_raises(self):
        """Polygon entirely outside the image should raise ValueError."""
        labels = np.zeros((10, 10), dtype=np.int32)

        rows = np.array([100, 200, 150], dtype=float)
        cols = np.array([100, 100, 200], dtype=float)

        with pytest.raises(ValueError, match="no pixels"):
            rasterize_polygon(labels, rows, cols)

    def test_polygon_modifies_in_place(self):
        """labels array should be modified in-place."""
        labels = np.zeros((20, 20), dtype=np.int32)
        original_id = id(labels)

        rows = np.array([2, 8, 5], dtype=float)
        cols = np.array([2, 2, 8], dtype=float)

        rasterize_polygon(labels, rows, cols)
        assert id(labels) == original_id
        assert labels.max() > 0


# ---------------------------------------------------------------------------
# delete_label_from_array
# ---------------------------------------------------------------------------


class TestDeleteLabelFromArray:
    """Tests for delete_label_from_array()."""

    def test_fills_label_with_zero(self):
        """All pixels with the target label should become 0."""
        labels = np.array([
            [1, 1, 0, 2],
            [1, 0, 0, 2],
            [0, 0, 3, 3],
        ], dtype=np.int32)

        result = delete_label_from_array(labels, 1)

        assert result is True
        assert not (labels == 1).any()
        # Other labels should be untouched
        assert (labels == 2).sum() == 2
        assert (labels == 3).sum() == 2

    def test_returns_false_for_missing_label(self):
        """Should return False if label doesn't exist in the array."""
        labels = np.array([[1, 2], [3, 0]], dtype=np.int32)

        result = delete_label_from_array(labels, 99)

        assert result is False
        # Array should be unchanged
        assert labels[0, 0] == 1

    def test_delete_preserves_other_labels(self):
        """Deleting one label should not affect others."""
        labels = np.array([
            [1, 1, 2, 2],
            [1, 1, 2, 2],
            [3, 3, 4, 4],
            [3, 3, 4, 4],
        ], dtype=np.int32)

        delete_label_from_array(labels, 2)

        assert (labels == 1).sum() == 4
        assert (labels == 2).sum() == 0
        assert (labels == 3).sum() == 4
        assert (labels == 4).sum() == 4

    def test_delete_background_returns_false(self):
        """Trying to delete label 0 when no 0s exist returns False on
        all-nonzero array, but True if zeros present and label_id=0."""
        labels = np.array([[1, 2], [3, 4]], dtype=np.int32)
        # No zeros in array, deleting 0 does nothing
        result = delete_label_from_array(labels, 0)
        assert result is False

    def test_modifies_in_place(self):
        """Array should be modified in-place."""
        labels = np.array([[5, 5], [0, 0]], dtype=np.int32)
        original_id = id(labels)

        delete_label_from_array(labels, 5)

        assert id(labels) == original_id
        assert labels.max() == 0
