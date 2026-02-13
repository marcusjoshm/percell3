"""Tests for percell3.io.transforms."""

import numpy as np
import pytest
import tifffile

from percell3.io.models import ZTransform
from percell3.io.transforms import (
    apply_z_transform,
    project_mean,
    project_mip,
    project_sum,
)


class TestProjectMip:
    def test_basic(self):
        stack = np.array([
            [[1, 2], [3, 4]],
            [[5, 6], [7, 8]],
            [[3, 1], [2, 9]],
        ], dtype=np.uint16)
        result = project_mip(stack)
        expected = np.array([[5, 6], [7, 9]], dtype=np.uint16)
        np.testing.assert_array_equal(result, expected)

    def test_preserves_dtype(self):
        stack = np.ones((3, 4, 4), dtype=np.uint8) * 100
        result = project_mip(stack)
        assert result.dtype == np.uint8


class TestProjectSum:
    def test_basic(self):
        stack = np.array([
            [[1, 2], [3, 4]],
            [[5, 6], [7, 8]],
        ], dtype=np.uint16)
        result = project_sum(stack)
        expected = np.array([[6, 8], [10, 12]], dtype=np.uint16)
        np.testing.assert_array_equal(result, expected)


class TestProjectMean:
    def test_basic(self):
        stack = np.array([
            [[10, 20], [30, 40]],
            [[30, 40], [50, 60]],
        ], dtype=np.uint16)
        result = project_mean(stack)
        expected = np.array([[20, 30], [40, 50]], dtype=np.uint16)
        np.testing.assert_array_equal(result, expected)

    def test_preserves_dtype(self):
        stack = np.ones((3, 4, 4), dtype=np.uint8) * 100
        result = project_mean(stack)
        assert result.dtype == np.uint8


class TestApplyZTransform:
    def test_mip(self, tmp_path):
        slices = []
        for i in range(3):
            data = np.ones((8, 8), dtype=np.uint16) * (i + 1) * 10
            p = tmp_path / f"z{i:02d}.tif"
            tifffile.imwrite(str(p), data)
            slices.append(p)

        result = apply_z_transform(slices, ZTransform(method="mip"))
        assert result.shape == (8, 8)
        assert result[0, 0] == 30  # max of 10, 20, 30

    def test_slice(self, tmp_path):
        slices = []
        for i in range(3):
            data = np.ones((8, 8), dtype=np.uint16) * (i + 1) * 10
            p = tmp_path / f"z{i:02d}.tif"
            tifffile.imwrite(str(p), data)
            slices.append(p)

        result = apply_z_transform(slices, ZTransform(method="slice", slice_index=1))
        assert result[0, 0] == 20  # second slice

    def test_slice_out_of_range(self, tmp_path):
        p = tmp_path / "z00.tif"
        tifffile.imwrite(str(p), np.zeros((8, 8), dtype=np.uint16))

        with pytest.raises(ValueError, match="out of range"):
            apply_z_transform([p], ZTransform(method="slice", slice_index=5))

    def test_slice_requires_index(self, tmp_path):
        p = tmp_path / "z00.tif"
        tifffile.imwrite(str(p), np.zeros((8, 8), dtype=np.uint16))

        with pytest.raises(ValueError, match="slice_index is required"):
            apply_z_transform([p], ZTransform(method="slice"))

    def test_unknown_method_raises(self, tmp_path):
        p = tmp_path / "z00.tif"
        tifffile.imwrite(str(p), np.zeros((8, 8), dtype=np.uint16))

        with pytest.raises(ValueError, match="Unknown"):
            apply_z_transform([p], ZTransform(method="invalid"))

    def test_mean(self, tmp_path):
        slices = []
        for i in range(2):
            data = np.ones((8, 8), dtype=np.uint16) * (i + 1) * 10
            p = tmp_path / f"z{i:02d}.tif"
            tifffile.imwrite(str(p), data)
            slices.append(p)

        result = apply_z_transform(slices, ZTransform(method="mean"))
        assert result[0, 0] == 15  # mean of 10, 20
        assert result.dtype == np.uint16
