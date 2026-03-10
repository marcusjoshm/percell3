"""TIFF reading utilities for PerCell 4.

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
