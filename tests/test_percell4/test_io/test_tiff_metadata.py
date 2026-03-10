"""Tests for percell4.io.tiff — _extract_pixel_size and read_tiff_metadata."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, patch

import numpy as np
import pytest
import tifffile

from percell4.io.tiff import _extract_pixel_size, read_tiff_metadata


# ---------------------------------------------------------------------------
# Helpers: build mock TiffFile objects
# ---------------------------------------------------------------------------


def _make_mock_tif(
    *,
    ome_metadata: str | None = None,
    imagej_metadata: dict | None = None,
    x_resolution: tuple[int, int] | None = None,
    resolution_unit: int | None = None,
) -> MagicMock:
    """Build a mock tifffile.TiffFile with controllable metadata."""
    tif = MagicMock()
    tif.ome_metadata = ome_metadata
    tif.imagej_metadata = imagej_metadata

    tags = {}
    if x_resolution is not None:
        tag_xr = MagicMock()
        tag_xr.value = x_resolution
        tags["XResolution"] = tag_xr
    if resolution_unit is not None:
        tag_ru = MagicMock()
        tag_ru.value = resolution_unit
        tags["ResolutionUnit"] = tag_ru

    page = MagicMock()
    page.tags = tags
    tif.pages = [page]

    return tif


# ---------------------------------------------------------------------------
# 1. OME-XML extraction
# ---------------------------------------------------------------------------


class TestExtractPixelSizeOmeXml:
    """Test _extract_pixel_size with OME-XML metadata."""

    def test_ome_xml_um(self) -> None:
        """PhysicalSizeX in micrometers is returned directly."""
        xml = (
            '<?xml version="1.0"?>'
            '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06">'
            '<Image><Pixels PhysicalSizeX="0.325" PhysicalSizeXUnit="\u00b5m"/>'
            "</Image></OME>"
        )
        tif = _make_mock_tif(ome_metadata=xml)
        assert _extract_pixel_size(tif) == pytest.approx(0.325)

    def test_ome_xml_nm(self) -> None:
        """PhysicalSizeX in nanometers is converted to um."""
        xml = (
            '<?xml version="1.0"?>'
            '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06">'
            '<Image><Pixels PhysicalSizeX="325" PhysicalSizeXUnit="nm"/>'
            "</Image></OME>"
        )
        tif = _make_mock_tif(ome_metadata=xml)
        assert _extract_pixel_size(tif) == pytest.approx(0.325)

    def test_ome_xml_mm(self) -> None:
        """PhysicalSizeX in millimeters is converted to um."""
        xml = (
            '<?xml version="1.0"?>'
            '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06">'
            '<Image><Pixels PhysicalSizeX="0.001" PhysicalSizeXUnit="mm"/>'
            "</Image></OME>"
        )
        tif = _make_mock_tif(ome_metadata=xml)
        assert _extract_pixel_size(tif) == pytest.approx(1.0)

    def test_ome_xml_default_unit_assumed_um(self) -> None:
        """Without PhysicalSizeXUnit, assumes micrometers."""
        xml = (
            '<?xml version="1.0"?>'
            '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06">'
            '<Image><Pixels PhysicalSizeX="0.5"/>'
            "</Image></OME>"
        )
        tif = _make_mock_tif(ome_metadata=xml)
        # Default unit is um
        assert _extract_pixel_size(tif) == pytest.approx(0.5)

    def test_ome_xml_no_pixels_element(self) -> None:
        """Returns None when OME-XML has no Pixels element."""
        xml = (
            '<?xml version="1.0"?>'
            '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06">'
            "<Image/></OME>"
        )
        tif = _make_mock_tif(ome_metadata=xml)
        assert _extract_pixel_size(tif) is None


# ---------------------------------------------------------------------------
# 2. ImageJ metadata
# ---------------------------------------------------------------------------


class TestExtractPixelSizeImageJ:
    """Test _extract_pixel_size with ImageJ metadata."""

    def test_imagej_spacing_micron(self) -> None:
        """ImageJ spacing in microns is returned directly."""
        tif = _make_mock_tif(
            imagej_metadata={"spacing": 0.65, "unit": "micron"}
        )
        assert _extract_pixel_size(tif) == pytest.approx(0.65)

    def test_imagej_spacing_um(self) -> None:
        """ImageJ spacing with unit 'um' is accepted."""
        tif = _make_mock_tif(
            imagej_metadata={"spacing": 0.325, "unit": "um"}
        )
        assert _extract_pixel_size(tif) == pytest.approx(0.325)

    def test_imagej_no_spacing(self) -> None:
        """Returns None when ImageJ metadata has no spacing."""
        tif = _make_mock_tif(imagej_metadata={"ImageWidth": 1024})
        assert _extract_pixel_size(tif) is None


# ---------------------------------------------------------------------------
# 3. TIFF resolution tags
# ---------------------------------------------------------------------------


class TestExtractPixelSizeResolutionTags:
    """Test _extract_pixel_size with TIFF resolution tags."""

    def test_resolution_centimeters(self) -> None:
        """XResolution in cm is converted to um."""
        # 10000 pixels per cm = 1 um/pixel
        tif = _make_mock_tif(
            x_resolution=(10000, 1), resolution_unit=3,
        )
        assert _extract_pixel_size(tif) == pytest.approx(1.0)

    def test_resolution_inches(self) -> None:
        """XResolution in inches is converted to um."""
        # 25400 pixels per inch = 1 um/pixel
        tif = _make_mock_tif(
            x_resolution=(25400, 1), resolution_unit=2,
        )
        assert _extract_pixel_size(tif) == pytest.approx(1.0)

    def test_resolution_fractional(self) -> None:
        """Fractional XResolution tuple is handled correctly."""
        # 5000 pixels per cm = 2 um/pixel
        tif = _make_mock_tif(
            x_resolution=(5000, 1), resolution_unit=3,
        )
        assert _extract_pixel_size(tif) == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# 4. Missing metadata
# ---------------------------------------------------------------------------


class TestExtractPixelSizeMissing:
    """Test _extract_pixel_size when no metadata is available."""

    def test_returns_none_when_nothing_available(self) -> None:
        """Returns None if no metadata source has pixel size."""
        tif = _make_mock_tif()
        assert _extract_pixel_size(tif) is None


# ---------------------------------------------------------------------------
# 5. read_tiff_metadata integration
# ---------------------------------------------------------------------------


class TestReadTiffMetadata:
    """Test read_tiff_metadata with real TIFF files."""

    def test_basic_metadata(self, tmp_path: Path) -> None:
        """Shape and dtype are always returned."""
        arr = np.zeros((32, 64), dtype=np.uint16)
        path = tmp_path / "test.tif"
        tifffile.imwrite(str(path), arr)

        meta = read_tiff_metadata(path)

        assert meta["shape"] == (32, 64)
        assert meta["dtype"] == "uint16"
        # pixel_size_um may be None for a plain TIFF
        assert "pixel_size_um" in meta

    def test_metadata_with_resolution_tags(self, tmp_path: Path) -> None:
        """Resolution tags are extracted when present."""
        arr = np.zeros((16, 16), dtype=np.uint8)
        path = tmp_path / "calibrated.tif"
        # Write with resolution metadata (10000 px/cm = 1 um/px)
        tifffile.imwrite(
            str(path),
            arr,
            resolution=(10000, 10000),
            resolutionunit=tifffile.RESUNIT.CENTIMETER,
        )

        meta = read_tiff_metadata(path)
        assert meta["pixel_size_um"] == pytest.approx(1.0)
