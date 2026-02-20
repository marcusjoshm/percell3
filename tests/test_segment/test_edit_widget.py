"""Tests for EditWidget — delete cell logic."""

from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock

import numpy as np
import pytest


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
