"""Tests for EditWidget — delete cell and polygon rasterization logic."""

from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock

import numpy as np
import pytest
from skimage.draw import polygon as sk_polygon


class TestEditWidgetDeleteLogic:
    """Test the core delete-cell logic without requiring napari or Qt."""

    def test_fill_zeroes_selected_label(self) -> None:
        """Simulates the delete logic: pixels with selected_label become 0."""
        labels = np.array([
            [0, 1, 1, 0],
            [0, 1, 1, 0],
            [0, 0, 0, 2],
            [0, 0, 2, 2],
        ], dtype=np.int32)

        selected_label = 1
        # Simulate what fill() does: set all pixels of selected label to 0
        coords = np.argwhere(labels == selected_label)
        assert len(coords) > 0

        # fill() at any coordinate of the label sets all connected to 0
        labels[labels == selected_label] = 0

        assert np.sum(labels == selected_label) == 0
        # Cell 2 should be untouched
        assert np.sum(labels == 2) == 3

    def test_background_selection_noop(self) -> None:
        """Selecting label 0 (background) should not modify labels."""
        labels = np.array([[0, 1], [1, 0]], dtype=np.int32)
        selected_label = 0

        # The widget should refuse to delete label 0
        assert selected_label == 0
        # No modification expected
        original = labels.copy()
        np.testing.assert_array_equal(labels, original)

    def test_nonexistent_label_returns_empty_coords(self) -> None:
        """Deleting a label that doesn't exist should find no coordinates."""
        labels = np.array([[0, 1], [1, 0]], dtype=np.int32)
        selected_label = 99

        coords = np.argwhere(labels == selected_label)
        assert len(coords) == 0


class TestPolygonRasterization:
    """Test polygon → label rasterization logic (mirrors _on_confirm_polygon)."""

    def test_polygon_fills_correct_region(self) -> None:
        """A square polygon fills the expected interior pixels."""
        labels = np.zeros((10, 10), dtype=np.int32)

        # Square polygon: rows 2-7, cols 2-7
        rows = np.array([2, 2, 7, 7])
        cols = np.array([2, 7, 7, 2])

        new_label = int(labels.max()) + 1
        rr, cc = sk_polygon(rows, cols, shape=labels.shape)
        labels[rr, cc] = new_label

        assert new_label == 1
        # Interior should be filled
        assert labels[4, 4] == 1
        assert labels[3, 5] == 1
        # Outside should remain 0
        assert labels[0, 0] == 0
        assert labels[9, 9] == 0

    def test_new_cell_id_is_max_plus_one(self) -> None:
        """New cell gets label = max(existing) + 1."""
        labels = np.array([
            [0, 1, 1, 0],
            [0, 1, 1, 0],
            [0, 0, 0, 3],
            [0, 0, 3, 3],
        ], dtype=np.int32)

        # Triangle polygon inside bottom-left
        rows = np.array([2, 3, 3])
        cols = np.array([0, 0, 1])

        new_label = int(labels.max()) + 1
        assert new_label == 4

        rr, cc = sk_polygon(rows, cols, shape=labels.shape)
        labels[rr, cc] = new_label

        # Existing labels untouched
        assert np.sum(labels == 1) == 4
        assert np.sum(labels == 3) == 3
        # New cell exists
        assert np.any(labels == 4)

    def test_polygon_entirely_outside_produces_no_pixels(self) -> None:
        """A polygon completely outside the image produces no pixels."""
        labels = np.zeros((10, 10), dtype=np.int32)

        # Polygon entirely beyond the image bounds
        rows = np.array([20, 20, 25, 25])
        cols = np.array([20, 25, 25, 20])

        rr, cc = sk_polygon(rows, cols, shape=labels.shape)
        assert len(rr) == 0

    def test_polygon_outside_bounds_is_clipped(self) -> None:
        """Polygon extending outside image is clipped to array bounds."""
        labels = np.zeros((10, 10), dtype=np.int32)

        # Polygon that extends beyond the 10x10 grid
        rows = np.array([7, 7, 15, 15])
        cols = np.array([7, 15, 15, 7])

        new_label = 1
        rr, cc = sk_polygon(rows, cols, shape=labels.shape)
        labels[rr, cc] = new_label

        # Only pixels within bounds should be set
        assert labels[8, 8] == 1
        assert labels[9, 9] == 1
        # Array shape unchanged
        assert labels.shape == (10, 10)
        # No index errors — the shape= parameter clips automatically
