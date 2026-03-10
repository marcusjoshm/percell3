"""TIFF reading and metadata extraction via tifffile.

Pure pixel-reading functions with no database or Zarr dependencies.
Uses tifffile for all TIFF I/O.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


def read_tiff(path: Path) -> np.ndarray:
    """Read a TIFF file into a numpy array.

    Args:
        path: Path to the TIFF file.

    Returns:
        Numpy array with the image data.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    import tifffile

    return tifffile.imread(str(path))


def read_tiff_series(directory: Path, pattern: str = "*.tif") -> list[tuple[str, np.ndarray]]:
    """Read all TIFFs in a directory matching a glob pattern.

    Args:
        directory: Directory to scan.
        pattern: Glob pattern for TIFF files.

    Returns:
        List of (name, array) tuples sorted by filename.
        *name* is the file stem (no extension).

    Raises:
        FileNotFoundError: If the directory does not exist.
    """
    import tifffile

    directory = Path(directory)
    if not directory.exists():
        raise FileNotFoundError(f"Directory does not exist: {directory}")

    results: list[tuple[str, np.ndarray]] = []
    for tiff_path in sorted(directory.glob(pattern)):
        if tiff_path.is_file():
            arr = tifffile.imread(str(tiff_path))
            results.append((tiff_path.stem, arr))

    return results


def read_tiff_metadata(path: Path) -> dict:
    """Extract metadata from a TIFF file without reading pixel data.

    Tries OME-XML first, then ImageJ metadata, then resolution tags.

    Args:
        path: Path to the TIFF file.

    Returns:
        Dict with keys: 'shape', 'dtype', 'pixel_size_um'.
        pixel_size_um may be None if not found.
    """
    import tifffile

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


def _extract_pixel_size(tif: "tifffile.TiffFile") -> float | None:
    """Try to extract pixel size in micrometers from TIFF metadata.

    Checks in order:
      1. OME-XML metadata for PhysicalSizeX + unit conversion
      2. ImageJ metadata for 'spacing' key
      3. TIFF resolution tags XResolution + ResolutionUnit

    Supported units: um/micron, nm, mm, cm, inch.

    Args:
        tif: An open tifffile.TiffFile instance.

    Returns:
        Pixel size in micrometers, or None if not found.
    """
    # 1. Try OME-XML
    if tif.ome_metadata:
        try:
            from defusedxml.ElementTree import fromstring as safe_fromstring

            root = safe_fromstring(tif.ome_metadata)
            ns = {"ome": "http://www.openmicroscopy.org/Schemas/OME/2016-06"}
            pixels = root.find(".//ome:Pixels", ns)
            if pixels is None:
                # Try without namespace
                pixels = root.find(".//{*}Pixels")
            if pixels is not None:
                ps_x = pixels.get("PhysicalSizeX")
                unit = pixels.get("PhysicalSizeXUnit", "\u00b5m")
                if ps_x is not None:
                    value = float(ps_x)
                    if unit in ("\u00b5m", "um", "micron"):
                        return value
                    if unit == "nm":
                        return value / 1000.0
                    if unit in ("mm", "millimeter"):
                        return value * 1000.0
                    if unit in ("cm", "centimeter"):
                        return value * 10000.0
                    return value  # assume um
        except Exception:
            pass

    # 2. Try ImageJ metadata
    if tif.imagej_metadata:
        try:
            ij = tif.imagej_metadata
            if "spacing" in ij:
                unit = ij.get("unit", "micron")
                spacing = float(ij["spacing"])
                if unit in ("micron", "um", "\u00b5m"):
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
                    return 10000.0 / pixels_per_unit  # cm -> um
                if res_unit == 2:  # inch
                    return 25400.0 / pixels_per_unit  # inch -> um
        except Exception:
            pass

    return None
