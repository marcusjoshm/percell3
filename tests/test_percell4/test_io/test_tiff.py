"""Tests for percell4.io.tiff — TIFF reading utilities."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import tifffile

from percell4.io.tiff import read_tiff, read_tiff_series


class TestReadTiff:
    """Tests for read_tiff()."""

    def test_round_trip(self, tmp_path: Path) -> None:
        """Write a TIFF, read it back, verify pixel values match."""
        arr = np.random.randint(0, 65535, (64, 64), dtype=np.uint16)
        path = tmp_path / "test.tif"
        tifffile.imwrite(str(path), arr)

        result = read_tiff(path)

        np.testing.assert_array_equal(result, arr)

    def test_read_float_tiff(self, tmp_path: Path) -> None:
        """Float32 TIFF round-trips correctly."""
        arr = np.random.rand(32, 32).astype(np.float32)
        path = tmp_path / "float.tif"
        tifffile.imwrite(str(path), arr)

        result = read_tiff(path)

        np.testing.assert_allclose(result, arr, rtol=1e-6)

    def test_read_3d_tiff(self, tmp_path: Path) -> None:
        """Multi-page (3D) TIFF preserves shape."""
        arr = np.random.randint(0, 255, (5, 32, 32), dtype=np.uint8)
        path = tmp_path / "stack.tif"
        tifffile.imwrite(str(path), arr)

        result = read_tiff(path)

        assert result.shape == (5, 32, 32)
        np.testing.assert_array_equal(result, arr)


class TestReadTiffSeries:
    """Tests for read_tiff_series()."""

    def test_reads_all_tiffs_in_directory(self, tmp_path: Path) -> None:
        """All matching TIFFs are read and returned as (name, array) pairs."""
        arr1 = np.zeros((16, 16), dtype=np.uint16)
        arr2 = np.ones((16, 16), dtype=np.uint16)

        tifffile.imwrite(str(tmp_path / "alpha.tif"), arr1)
        tifffile.imwrite(str(tmp_path / "beta.tif"), arr2)

        results = read_tiff_series(tmp_path)

        assert len(results) == 2
        assert results[0][0] == "alpha"
        assert results[1][0] == "beta"
        np.testing.assert_array_equal(results[0][1], arr1)
        np.testing.assert_array_equal(results[1][1], arr2)

    def test_empty_directory(self, tmp_path: Path) -> None:
        """Empty directory returns empty list."""
        results = read_tiff_series(tmp_path)
        assert results == []

    def test_custom_pattern(self, tmp_path: Path) -> None:
        """Custom glob pattern filters files correctly."""
        arr = np.zeros((8, 8), dtype=np.uint8)
        tifffile.imwrite(str(tmp_path / "image_001.tif"), arr)
        tifffile.imwrite(str(tmp_path / "mask_001.tif"), arr)

        results = read_tiff_series(tmp_path, pattern="image_*.tif")

        assert len(results) == 1
        assert results[0][0] == "image_001"

    def test_nonexistent_directory(self) -> None:
        """FileNotFoundError raised for missing directory."""
        with pytest.raises(FileNotFoundError):
            read_tiff_series(Path("/nonexistent"))

    def test_sorted_by_name(self, tmp_path: Path) -> None:
        """Results are sorted alphabetically by filename."""
        arr = np.zeros((8, 8), dtype=np.uint8)
        tifffile.imwrite(str(tmp_path / "z.tif"), arr)
        tifffile.imwrite(str(tmp_path / "a.tif"), arr)

        results = read_tiff_series(tmp_path)
        names = [r[0] for r in results]
        assert names == ["a", "z"]
