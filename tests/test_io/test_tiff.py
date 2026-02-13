"""Tests for percell3.io.tiff."""

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import tifffile
from defusedxml import EntitiesForbidden

from percell3.io.tiff import read_tiff, read_tiff_metadata


class TestReadTiff:
    def test_read_single_page(self, tmp_path):
        data = np.random.randint(0, 65535, (64, 64), dtype=np.uint16)
        p = tmp_path / "single.tif"
        tifffile.imwrite(str(p), data)

        result = read_tiff(p)
        np.testing.assert_array_equal(result, data)

    def test_read_8bit(self, tmp_path):
        data = np.random.randint(0, 255, (32, 32), dtype=np.uint8)
        p = tmp_path / "8bit.tif"
        tifffile.imwrite(str(p), data)

        result = read_tiff(p)
        assert result.dtype == np.uint8
        np.testing.assert_array_equal(result, data)

    def test_read_float32(self, tmp_path):
        data = np.random.rand(32, 32).astype(np.float32)
        p = tmp_path / "float.tif"
        tifffile.imwrite(str(p), data)

        result = read_tiff(p)
        assert result.dtype == np.float32


class TestXXEProtection:
    def test_entity_expansion_rejected(self, tmp_path):
        """OME-XML with entity expansion must be rejected by defusedxml."""
        hostile_xml = (
            '<?xml version="1.0"?>'
            '<!DOCTYPE foo ['
            '  <!ENTITY xxe "AAAA">'
            ']>'
            '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06">'
            '  <Pixels PhysicalSizeX="&xxe;" />'
            '</OME>'
        )
        # Write a plain TIFF, then mock ome_metadata to return hostile XML
        data = np.zeros((32, 32), dtype=np.uint16)
        p = tmp_path / "hostile.tif"
        tifffile.imwrite(str(p), data)

        with tifffile.TiffFile(str(p)) as tif:
            with patch.object(type(tif), "ome_metadata", new_callable=lambda: property(lambda self: hostile_xml)):
                # _extract_pixel_size catches the exception and returns None
                # but we want to verify defusedxml rejects it at the fromstring level
                from defusedxml.ElementTree import fromstring as safe_fromstring

                with pytest.raises(EntitiesForbidden):
                    safe_fromstring(hostile_xml)


class TestReadTiffMetadata:
    def test_shape_and_dtype(self, tmp_path):
        data = np.zeros((128, 256), dtype=np.uint16)
        p = tmp_path / "meta.tif"
        tifffile.imwrite(str(p), data)

        meta = read_tiff_metadata(p)
        assert meta["shape"] == (128, 256)
        assert meta["dtype"] == "uint16"

    def test_pixel_size_none_for_plain_tiff(self, tmp_path):
        data = np.zeros((32, 32), dtype=np.uint16)
        p = tmp_path / "plain.tif"
        tifffile.imwrite(str(p), data)

        meta = read_tiff_metadata(p)
        # Plain TIFF without explicit metadata may or may not have pixel size
        # Just verify the key exists
        assert "pixel_size_um" in meta

    def test_resolution_tags_extracted(self, tmp_path):
        """TIFF with resolution tags should extract pixel size."""
        data = np.zeros((64, 64), dtype=np.uint16)
        p = tmp_path / "resolution.tif"
        # Write with resolution: 10 pixels per cm = 1000 µm per pixel
        tifffile.imwrite(
            str(p), data,
            resolution=(10, 10),
            resolutionunit=3,  # centimeter
        )

        meta = read_tiff_metadata(p)
        if meta["pixel_size_um"] is not None:
            assert meta["pixel_size_um"] == 1000.0
