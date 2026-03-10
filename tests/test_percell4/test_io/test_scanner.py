"""Tests for percell4.io.scanner — file discovery."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import tifffile

from percell4.io.scanner import FileInfo, scan_directory


class TestScanDirectory:
    """Tests for scan_directory()."""

    def test_scan_finds_tiff_files(self, tmp_path: Path) -> None:
        """TIFF files are discovered and returned as FileInfo."""
        (tmp_path / "image_001.tif").write_bytes(b"\x00")
        (tmp_path / "image_002.tiff").write_bytes(b"\x00")

        results = scan_directory(tmp_path)

        assert len(results) == 2
        assert all(isinstance(r, FileInfo) for r in results)
        names = [r.name for r in results]
        assert "image_001" in names
        assert "image_002" in names

    def test_scan_empty_directory(self, tmp_path: Path) -> None:
        """An empty directory returns an empty list."""
        results = scan_directory(tmp_path)
        assert results == []

    def test_scan_filters_by_extension(self, tmp_path: Path) -> None:
        """Only files matching requested extensions are returned."""
        (tmp_path / "image.tif").write_bytes(b"\x00")
        (tmp_path / "notes.txt").write_bytes(b"\x00")
        (tmp_path / "data.csv").write_bytes(b"\x00")

        results = scan_directory(tmp_path, extensions=(".tif",))
        assert len(results) == 1
        assert results[0].name == "image"
        assert results[0].format == "tiff"

    def test_scan_nonexistent_directory(self) -> None:
        """FileNotFoundError raised for missing directory."""
        with pytest.raises(FileNotFoundError):
            scan_directory(Path("/nonexistent/path"))

    def test_scan_file_not_directory(self, tmp_path: Path) -> None:
        """ValueError raised if path is a file, not a directory."""
        f = tmp_path / "not_a_dir.tif"
        f.write_bytes(b"\x00")
        with pytest.raises(ValueError, match="not a directory"):
            scan_directory(f)

    def test_scan_sorted_by_name(self, tmp_path: Path) -> None:
        """Results are sorted alphabetically by filename."""
        (tmp_path / "z_last.tif").write_bytes(b"\x00")
        (tmp_path / "a_first.tif").write_bytes(b"\x00")
        (tmp_path / "m_middle.tif").write_bytes(b"\x00")

        results = scan_directory(tmp_path)
        names = [r.name for r in results]
        assert names == ["a_first", "m_middle", "z_last"]

    def test_scan_format_detection(self, tmp_path: Path) -> None:
        """Format field matches the file extension."""
        (tmp_path / "a.tif").write_bytes(b"\x00")
        (tmp_path / "b.tiff").write_bytes(b"\x00")
        (tmp_path / "c.lif").write_bytes(b"\x00")
        (tmp_path / "d.czi").write_bytes(b"\x00")

        results = scan_directory(tmp_path)
        fmt_map = {r.name: r.format for r in results}
        assert fmt_map["a"] == "tiff"
        assert fmt_map["b"] == "tiff"
        assert fmt_map["c"] == "lif"
        assert fmt_map["d"] == "czi"

    def test_scan_skips_symlinks(self, tmp_path: Path) -> None:
        """Symlinks are ignored to prevent directory escape."""
        real = tmp_path / "real.tif"
        real.write_bytes(b"\x00")
        link = tmp_path / "link.tif"
        link.symlink_to(real)

        results = scan_directory(tmp_path)
        assert len(results) == 1
        assert results[0].name == "real"

    def test_scan_case_insensitive_extension(self, tmp_path: Path) -> None:
        """Extension matching is case-insensitive."""
        (tmp_path / "image.TIF").write_bytes(b"\x00")
        (tmp_path / "image2.Tiff").write_bytes(b"\x00")

        results = scan_directory(tmp_path)
        assert len(results) == 2

    def test_pixel_size_um_extracted_from_tiff(self, tmp_path: Path) -> None:
        """pixel_size_um is populated from TIFF resolution tags."""
        arr = np.zeros((16, 16), dtype=np.uint8)
        path = tmp_path / "calibrated.tif"
        # 10000 pixels/cm = 1 um/pixel
        tifffile.imwrite(
            str(path), arr,
            resolution=(10000, 10000),
            resolutionunit=tifffile.RESUNIT.CENTIMETER,
        )

        results = scan_directory(tmp_path, extensions=(".tif",))
        assert len(results) == 1
        assert results[0].pixel_size_um == pytest.approx(1.0)

    def test_pixel_size_um_none_without_metadata(self, tmp_path: Path) -> None:
        """pixel_size_um is None when TIFF has no calibration metadata."""
        arr = np.zeros((16, 16), dtype=np.uint8)
        path = tmp_path / "plain.tif"
        tifffile.imwrite(str(path), arr)

        results = scan_directory(tmp_path, extensions=(".tif",))
        assert len(results) == 1
        assert results[0].pixel_size_um is None

    def test_pixel_size_um_none_for_non_tiff(self, tmp_path: Path) -> None:
        """Non-TIFF files always have pixel_size_um=None."""
        (tmp_path / "data.lif").write_bytes(b"\x00")

        results = scan_directory(tmp_path, extensions=(".lif",))
        assert len(results) == 1
        assert results[0].pixel_size_um is None
