"""TIFF reading and metadata extraction via tifffile."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import tifffile


def read_tiff(path: Path) -> np.ndarray:
    """Read a TIFF file into a numpy array.

    Args:
        path: Path to the TIFF file.

    Returns:
        Numpy array with the image data.
    """
    return tifffile.imread(str(path))


def read_tiff_metadata(path: Path) -> dict:
    """Extract metadata from a TIFF file without reading pixel data.

    Tries OME-XML first, then ImageJ metadata, then resolution tags.

    Args:
        path: Path to the TIFF file.

    Returns:
        Dict with keys: 'shape', 'dtype', 'pixel_size_um'.
        pixel_size_um may be None if not found.
    """
    with tifffile.TiffFile(str(path)) as tif:
        page = tif.pages[0]
        shape = page.shape
        dtype = str(page.dtype)

        pixel_size_um = _extract_pixel_size(tif)

    return {
        "shape": shape,
        "dtype": dtype,
        "pixel_size_um": pixel_size_um,
    }


def _extract_pixel_size(tif: tifffile.TiffFile) -> float | None:
    """Try to extract pixel size in micrometers from TIFF metadata.

    Checks in order: OME-XML, ImageJ metadata, resolution tags.
    """
    # 1. Try OME-XML
    if tif.ome_metadata:
        try:
            import xml.etree.ElementTree as ET

            root = ET.fromstring(tif.ome_metadata)
            ns = {"ome": "http://www.openmicroscopy.org/Schemas/OME/2016-06"}
            pixels = root.find(".//ome:Pixels", ns)
            if pixels is None:
                # Try without namespace
                pixels = root.find(".//{*}Pixels")
            if pixels is not None:
                ps_x = pixels.get("PhysicalSizeX")
                unit = pixels.get("PhysicalSizeXUnit", "µm")
                if ps_x is not None:
                    value = float(ps_x)
                    if unit in ("µm", "um", "micron"):
                        return value
                    if unit == "nm":
                        return value / 1000.0
                    if unit in ("mm", "millimeter"):
                        return value * 1000.0
                    return value  # assume µm
        except Exception:
            pass

    # 2. Try ImageJ metadata
    if tif.imagej_metadata:
        try:
            ij = tif.imagej_metadata
            if "spacing" in ij:
                # ImageJ spacing is typically in the unit specified
                unit = ij.get("unit", "micron")
                spacing = float(ij["spacing"])
                if unit in ("micron", "um", "µm"):
                    return spacing
        except Exception:
            pass

    # 3. Try TIFF resolution tags
    page = tif.pages[0]
    tags = page.tags
    if "XResolution" in tags and "ResolutionUnit" in tags:
        try:
            x_res = tags["XResolution"].value
            res_unit = tags["ResolutionUnit"].value
            # x_res is a tuple (numerator, denominator)
            if isinstance(x_res, tuple) and len(x_res) == 2:
                pixels_per_unit = x_res[0] / x_res[1]
            else:
                pixels_per_unit = float(x_res)

            if pixels_per_unit > 0:
                # ResolutionUnit: 1=no unit, 2=inch, 3=centimeter
                if res_unit == 3:  # centimeter
                    return 10000.0 / pixels_per_unit  # cm -> µm
                if res_unit == 2:  # inch
                    return 25400.0 / pixels_per_unit  # inch -> µm
        except Exception:
            pass

    return None
