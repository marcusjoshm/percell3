"""Read ImageJ ROI .zip files and render to label images.

Ported from percell3.segment.imagej_roi_reader.  This module is pure
file parsing with no database dependencies.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from skimage.draw import polygon as draw_polygon

logger = logging.getLogger(__name__)


def _lazy_import_roifile():  # type: ignore[no-untyped-def]
    """Lazy-import roifile with a helpful error message."""
    try:
        from roifile import ROI_TYPE, roiread
        return roiread, ROI_TYPE
    except ImportError:
        raise ImportError(
            "The 'roifile' package is required for ImageJ ROI import. "
            "Install it with: pip install percell4[imagej]"
        ) from None


# ROI types that represent area regions (polygon-like outlines).
_AREA_ROI_TYPES: set[int] = set()  # populated on first use


def _get_area_roi_types() -> set[int]:
    """Return the set of ROI_TYPE values that represent area regions."""
    global _AREA_ROI_TYPES
    if _AREA_ROI_TYPES:
        return _AREA_ROI_TYPES
    _, ROI_TYPE = _lazy_import_roifile()
    _AREA_ROI_TYPES = {
        ROI_TYPE.POLYGON,
        ROI_TYPE.FREEHAND,
        ROI_TYPE.TRACED,
        ROI_TYPE.RECT,
        ROI_TYPE.OVAL,
    }
    return _AREA_ROI_TYPES


def read_imagej_rois(zip_path: Path) -> list[dict]:
    """Read ROI coordinates from an ImageJ .zip file.

    Reads polygon/freehand/traced/rect/oval ROIs and returns their
    coordinates.  Non-area ROI types (lines, points) are skipped.

    Args:
        zip_path: Path to the .zip file containing ImageJ ROIs.

    Returns:
        List of dicts with ``roi_index`` (1-based) and ``coordinates``
        (Nx2 array of (row, col) points).

    Raises:
        FileNotFoundError: If *zip_path* does not exist.
        ImportError: If the ``roifile`` package is not installed.
        ValueError: If the file contains no usable area ROIs.
    """
    roiread, _ROI_TYPE = _lazy_import_roifile()
    zip_path = Path(zip_path)
    if not zip_path.exists():
        raise FileNotFoundError(f"ROI file not found: {zip_path}")

    try:
        rois = roiread(str(zip_path))
    except Exception as exc:
        raise ValueError(
            f"Cannot read ImageJ ROIs from {zip_path.name}: {exc}"
        ) from exc

    if not isinstance(rois, list):
        rois = [rois]

    area_types = _get_area_roi_types()
    results: list[dict] = []
    skipped = 0

    for roi in rois:
        if roi.roitype not in area_types:
            skipped += 1
            continue

        coords = roi.coordinates()
        if coords is None or len(coords) < 3:
            skipped += 1
            continue

        # roifile returns (x, y), convert to (row, col) = (y, x)
        col = coords[:, 0]
        row = coords[:, 1]
        rc_coords = np.column_stack([row, col])

        results.append({
            "roi_index": len(results) + 1,
            "coordinates": rc_coords,
        })

    if not results:
        raise ValueError(
            f"No usable area ROIs found in {zip_path.name}. "
            f"Skipped {skipped} non-polygon ROI(s)."
        )

    return results


def rois_to_labels(
    zip_path: Path,
    image_shape: tuple[int, int],
) -> tuple[np.ndarray, dict[str, int]]:
    """Convert an ImageJ ROI .zip file to an integer label image.

    Reads polygon/freehand/traced ROIs from the .zip and rasterises each
    as a filled region in a 2-D label array.  ROIs that are not area types
    (lines, points, etc.) are silently skipped.

    Args:
        zip_path: Path to the .zip file containing ImageJ ROIs.
        image_shape: ``(height, width)`` of the target label image.

    Returns:
        A tuple of ``(labels, info)`` where *labels* is an int32 array with
        unique IDs per ROI (1-indexed, 0 = background) and *info* is a dict
        with ``roi_count`` and ``skipped_count``.

    Raises:
        FileNotFoundError: If *zip_path* does not exist.
        ValueError: If the file contains no usable area ROIs.
    """
    roiread, _ROI_TYPE = _lazy_import_roifile()
    zip_path = Path(zip_path)
    if not zip_path.exists():
        raise FileNotFoundError(f"ROI file not found: {zip_path}")

    try:
        rois = roiread(str(zip_path))
    except Exception as exc:
        raise ValueError(
            f"Cannot read ImageJ ROIs from {zip_path.name}: {exc}"
        ) from exc

    if not isinstance(rois, list):
        rois = [rois]

    area_types = _get_area_roi_types()
    labels = np.zeros(image_shape, dtype=np.int32)
    label_id = 0
    skipped = 0

    for roi in rois:
        if roi.roitype not in area_types:
            skipped += 1
            continue

        coords = roi.coordinates()
        if coords is None or len(coords) < 3:
            skipped += 1
            continue

        label_id += 1

        # roifile returns (x, y) but skimage expects (row, col) = (y, x)
        col = coords[:, 0]
        row = coords[:, 1]

        rr, cc = draw_polygon(row, col, shape=image_shape)
        if len(rr) > 0:
            labels[rr, cc] = label_id
        else:
            label_id -= 1
            skipped += 1

    if label_id == 0:
        raise ValueError(
            f"No usable area ROIs found in {zip_path.name}. "
            f"Skipped {skipped} non-polygon ROI(s)."
        )

    info = {
        "roi_count": label_id,
        "skipped_count": skipped,
    }
    return labels, info
