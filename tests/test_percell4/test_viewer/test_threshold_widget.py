"""Tests for threshold widget pure-logic helpers (no Qt required).

Tests compute_preview_mask and count_particles — the testable core
of the interactive threshold widget.
"""

from __future__ import annotations

import numpy as np
import pytest

from percell4.viewer.threshold_widget import compute_preview_mask, count_particles


# ---------------------------------------------------------------------------
# compute_preview_mask
# ---------------------------------------------------------------------------


class TestComputePreviewMask:
    """Tests for compute_preview_mask()."""

    def test_binary_above_threshold(self):
        """Pixels above threshold should be 1, at or below should be 0."""
        image = np.array([
            [10, 20, 30],
            [40, 50, 60],
        ], dtype=np.float32)

        mask = compute_preview_mask(image, 25.0)

        # 30, 40, 50, 60 are above 25
        assert mask.dtype == np.uint8
        assert mask[0, 0] == 0  # 10 <= 25
        assert mask[0, 1] == 0  # 20 <= 25
        assert mask[0, 2] == 1  # 30 > 25
        assert mask[1, 0] == 1  # 40 > 25
        assert mask[1, 1] == 1  # 50 > 25
        assert mask[1, 2] == 1  # 60 > 25

    def test_all_above_threshold(self):
        """When threshold is below all values, entire mask is True."""
        image = np.array([[100, 200], [300, 400]], dtype=np.float32)

        mask = compute_preview_mask(image, 0.0)

        assert mask.sum() == 4
        assert np.all(mask == 1)

    def test_all_below_threshold(self):
        """When threshold is above all values, mask is entirely False."""
        image = np.array([[1, 2], [3, 4]], dtype=np.float32)

        mask = compute_preview_mask(image, 100.0)

        assert mask.sum() == 0
        assert np.all(mask == 0)

    def test_exact_threshold_excluded(self):
        """Pixels exactly at threshold should be excluded (strict >)."""
        image = np.array([[10, 20, 30]], dtype=np.float32)

        mask = compute_preview_mask(image, 20.0)

        assert mask[0, 0] == 0  # 10 not > 20
        assert mask[0, 1] == 0  # 20 not > 20 (exact)
        assert mask[0, 2] == 1  # 30 > 20

    def test_returns_uint8(self):
        """Mask should be uint8 for napari compatibility."""
        image = np.ones((5, 5), dtype=np.float32) * 50

        mask = compute_preview_mask(image, 25.0)

        assert mask.dtype == np.uint8

    def test_preserves_shape(self):
        """Output mask should have the same shape as input image."""
        image = np.random.rand(100, 200).astype(np.float32) * 255

        mask = compute_preview_mask(image, 128.0)

        assert mask.shape == image.shape


# ---------------------------------------------------------------------------
# count_particles
# ---------------------------------------------------------------------------


class TestCountParticles:
    """Tests for count_particles()."""

    def test_returns_int(self):
        """Return value should be a Python int."""
        mask = np.array([[1, 0], [0, 1]], dtype=np.uint8)

        result = count_particles(mask)

        assert isinstance(result, int)

    def test_empty_mask_returns_zero(self):
        """An all-zero mask should return 0 particles."""
        mask = np.zeros((10, 10), dtype=np.uint8)

        result = count_particles(mask)

        assert result == 0

    def test_single_blob(self):
        """A single connected region should return 1."""
        mask = np.zeros((10, 10), dtype=np.uint8)
        mask[3:6, 3:6] = 1  # one 3x3 blob

        result = count_particles(mask)

        assert result == 1

    def test_two_separate_blobs(self):
        """Two disconnected regions should return 2."""
        mask = np.zeros((20, 20), dtype=np.uint8)
        mask[2:5, 2:5] = 1   # top-left blob
        mask[15:18, 15:18] = 1  # bottom-right blob

        result = count_particles(mask)

        assert result == 2

    def test_three_blobs(self):
        """Three disconnected regions should return 3."""
        mask = np.zeros((30, 30), dtype=np.uint8)
        mask[2:5, 2:5] = 1
        mask[15:18, 2:5] = 1
        mask[2:5, 25:28] = 1

        result = count_particles(mask)

        assert result == 3

    def test_touching_blobs_are_one(self):
        """Two adjacent blobs that share an edge should count as 1."""
        mask = np.zeros((10, 10), dtype=np.uint8)
        mask[3:6, 3:5] = 1
        mask[3:6, 5:8] = 1  # directly adjacent (share edge at col 5)

        result = count_particles(mask)

        assert result == 1

    def test_diagonal_blobs_are_separate(self):
        """Two diagonally-adjacent blobs should count as separate
        (scipy.ndimage.label uses 4-connectivity by default)."""
        mask = np.zeros((10, 10), dtype=np.uint8)
        mask[2, 2] = 1
        mask[3, 3] = 1  # diagonal only, not edge-connected

        result = count_particles(mask)

        assert result == 2

    def test_bool_mask_input(self):
        """Should work with bool dtype as well as uint8."""
        mask = np.zeros((10, 10), dtype=bool)
        mask[2:5, 2:5] = True

        result = count_particles(mask)

        assert result == 1
