"""Tests for percell3.io.scanner."""

from pathlib import Path

import numpy as np
import pytest
import tifffile

from percell3.io.models import TokenConfig
from percell3.io.scanner import FileScanner


class TestScanBasic:
    def test_scan_finds_tiff_files(self, tiff_dir):
        scanner = FileScanner()
        result = scanner.scan(tiff_dir)
        assert len(result.files) == 2

    def test_scan_parses_channel_tokens(self, tiff_dir):
        scanner = FileScanner()
        result = scanner.scan(tiff_dir)
        assert result.channels == ["00", "01"]

    def test_scan_parses_timepoint_tokens(self, tiff_dir):
        scanner = FileScanner()
        result = scanner.scan(tiff_dir)
        assert result.timepoints == ["00"]

    def test_scan_extracts_shape(self, tiff_dir):
        scanner = FileScanner()
        result = scanner.scan(tiff_dir)
        assert result.files[0].shape == (64, 64)

    def test_scan_extracts_dtype(self, tiff_dir):
        scanner = FileScanner()
        result = scanner.scan(tiff_dir)
        assert result.files[0].dtype == "uint16"

    def test_scan_source_path(self, tiff_dir):
        scanner = FileScanner()
        result = scanner.scan(tiff_dir)
        assert result.source_path == tiff_dir


class TestScanMultiRegion:
    def test_discovers_regions(self, tiff_dir_multichannel_multiregion):
        scanner = FileScanner()
        result = scanner.scan(tiff_dir_multichannel_multiregion)
        assert sorted(result.regions) == ["region1", "region2"]

    def test_discovers_channels(self, tiff_dir_multichannel_multiregion):
        scanner = FileScanner()
        result = scanner.scan(tiff_dir_multichannel_multiregion)
        assert result.channels == ["00", "01"]


class TestScanZStack:
    def test_discovers_z_slices(self, tiff_dir_with_z):
        scanner = FileScanner()
        result = scanner.scan(tiff_dir_with_z)
        assert result.z_slices == ["00", "01", "02"]
        assert result.channels == ["00"]


class TestScanEdgeCases:
    def test_nonexistent_path_raises(self):
        scanner = FileScanner()
        with pytest.raises(FileNotFoundError):
            scanner.scan(Path("/nonexistent/path"))

    def test_not_a_directory_raises(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("hello")
        scanner = FileScanner()
        with pytest.raises(ValueError, match="not a directory"):
            scanner.scan(f)

    def test_empty_directory_raises(self, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        scanner = FileScanner()
        with pytest.raises(ValueError, match="No TIFF files"):
            scanner.scan(d)

    def test_inconsistent_shapes_warns(self, tmp_path):
        d = tmp_path / "mixed"
        d.mkdir()
        tifffile.imwrite(str(d / "a_ch00.tif"), np.zeros((64, 64), dtype=np.uint16))
        tifffile.imwrite(str(d / "b_ch01.tif"), np.zeros((128, 128), dtype=np.uint16))

        scanner = FileScanner()
        result = scanner.scan(d)
        assert any("Inconsistent shapes" in w for w in result.warnings)


class TestSymlinkGuard:
    def test_symlinked_tiff_file_skipped(self, tmp_path):
        d = tmp_path / "data"
        d.mkdir()
        tifffile.imwrite(str(d / "real_ch00.tif"), np.zeros((32, 32), dtype=np.uint16))

        # Create symlink to a TIFF outside the directory
        external = tmp_path / "external.tif"
        tifffile.imwrite(str(external), np.zeros((32, 32), dtype=np.uint16))
        (d / "link_ch01.tif").symlink_to(external)

        scanner = FileScanner()
        result = scanner.scan(d)
        # Only the real file, not the symlink
        assert len(result.files) == 1
        assert result.channels == ["00"]

    def test_symlinked_directory_not_followed(self, tmp_path):
        d = tmp_path / "data"
        d.mkdir()
        tifffile.imwrite(str(d / "img_ch00.tif"), np.zeros((32, 32), dtype=np.uint16))

        # Create subdirectory with a TIFF, then symlink it
        external_dir = tmp_path / "external_dir"
        external_dir.mkdir()
        tifffile.imwrite(
            str(external_dir / "extra_ch01.tif"),
            np.zeros((32, 32), dtype=np.uint16),
        )
        (d / "linked_dir").symlink_to(external_dir)

        scanner = FileScanner()
        result = scanner.scan(d)
        # Should only find the real file, not files through symlinked dir
        assert len(result.files) == 1


class TestCustomTokenConfig:
    def test_custom_channel_pattern(self, tmp_path):
        d = tmp_path / "custom"
        d.mkdir()
        tifffile.imwrite(
            str(d / "img_C0.tif"), np.zeros((32, 32), dtype=np.uint16)
        )
        tifffile.imwrite(
            str(d / "img_C1.tif"), np.zeros((32, 32), dtype=np.uint16)
        )

        config = TokenConfig(channel=r"_C(\d+)")
        scanner = FileScanner()
        result = scanner.scan(d, token_config=config)
        assert result.channels == ["0", "1"]

    def test_custom_region_pattern(self, tmp_path):
        d = tmp_path / "custom"
        d.mkdir()
        tifffile.imwrite(
            str(d / "img_r01_ch00.tif"), np.zeros((32, 32), dtype=np.uint16)
        )
        tifffile.imwrite(
            str(d / "img_r02_ch00.tif"), np.zeros((32, 32), dtype=np.uint16)
        )

        config = TokenConfig(region=r"_r(\d+)")
        scanner = FileScanner()
        result = scanner.scan(d, token_config=config)
        assert result.regions == ["01", "02"]
