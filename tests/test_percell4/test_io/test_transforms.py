"""Tests for percell4.io.transforms — Z-projection operations."""

from __future__ import annotations

import numpy as np
import pytest

from percell4.io.transforms import project_z


class TestProjectZ:
    """Tests for project_z()."""

    def test_max_projection(self) -> None:
        """MIP returns per-pixel maximum along Z axis."""
        stack = np.array([
            [[1, 2], [3, 4]],
            [[5, 6], [7, 8]],
            [[0, 9], [1, 2]],
        ])

        result = project_z(stack, method="max")

        expected = np.array([[5, 9], [7, 8]])
        np.testing.assert_array_equal(result, expected)

    def test_mean_projection(self) -> None:
        """Mean projection preserves input dtype."""
        stack = np.array([
            [[3, 6], [9, 12]],
            [[6, 12], [18, 24]],
        ], dtype=np.uint16)

        result = project_z(stack, method="mean")

        # (3+6)/2=4, (6+12)/2=9, (9+18)/2=13, (12+24)/2=18
        # dtype truncation: mean then cast to uint16
        expected = np.array([[4, 9], [13, 18]], dtype=np.uint16)
        np.testing.assert_array_equal(result, expected)
        assert result.dtype == np.uint16

    def test_sum_projection(self) -> None:
        """Sum projection uses int64 for integer inputs to prevent overflow."""
        stack = np.array([
            [[100, 120], [50, 80]],
            [[100, 120], [50, 80]],
        ], dtype=np.uint8)

        result = project_z(stack, method="sum")

        expected = np.array([[200, 240], [100, 160]])
        np.testing.assert_array_equal(result, expected)
        # int64 for integer inputs to prevent overflow
        assert result.dtype == np.int64

    def test_sum_projection_float(self) -> None:
        """Sum of float stack preserves float dtype."""
        stack = np.array([
            [[1.5, 2.5]],
            [[3.5, 4.5]],
        ], dtype=np.float32)

        result = project_z(stack, method="sum")

        np.testing.assert_allclose(result, np.array([[5.0, 7.0]]))

    def test_invalid_method_raises(self) -> None:
        """Unknown projection method raises ValueError."""
        stack = np.zeros((3, 4, 4))

        with pytest.raises(ValueError, match="Unknown projection method"):
            project_z(stack, method="median")

    def test_default_method_is_max(self) -> None:
        """Default method parameter is 'max'."""
        stack = np.array([
            [[1, 2]],
            [[3, 4]],
        ])

        result_default = project_z(stack)
        result_max = project_z(stack, method="max")

        np.testing.assert_array_equal(result_default, result_max)

    def test_single_slice(self) -> None:
        """Single-slice stack returns unchanged 2D array."""
        stack = np.array([[[10, 20], [30, 40]]])

        for method in ("max", "mean", "sum"):
            result = project_z(stack, method=method)
            expected = np.array([[10, 20], [30, 40]])
            np.testing.assert_array_equal(result, expected)
