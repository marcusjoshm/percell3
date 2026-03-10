"""Pure numpy extraction of ROI properties from integer label images.

Ported from percell3.segment.label_processor with renaming:
    cell -> ROI, extract_cells -> extract_rois.

Uses scikit-image regionprops for bounding box and area computation.
"""

from __future__ import annotations

import numpy as np
from skimage.measure import regionprops


def extract_rois(
    labels: np.ndarray,
    min_area: int = 0,
    exclude_edge: bool = False,
) -> list[dict]:
    """Extract ROI properties from a 2D integer label image.

    Finds unique non-zero labels and computes bounding box and area for
    each.  Optionally filters by minimum area and edge-touching status.

    Args:
        labels: 2D integer array (Y, X) where pixel value = ROI ID,
            0 = background.
        min_area: Minimum area in pixels.  ROIs smaller than this are
            excluded.  0 means no filtering.
        exclude_edge: If True, ROIs whose bounding box touches the image
            border are excluded.

    Returns:
        List of dicts, one per retained ROI, with keys:
            ``label_id``, ``bbox_y``, ``bbox_x``, ``bbox_h``, ``bbox_w``,
            ``area_px``.
    """
    if labels.ndim != 2:
        raise ValueError(
            f"Labels must be 2D, got {labels.ndim}D with shape {labels.shape}"
        )

    if labels.max() == 0:
        return []

    h, w = labels.shape
    props = regionprops(labels)
    results: list[dict] = []

    for prop in props:
        area = int(prop.area)

        # Filter by minimum area
        if min_area > 0 and area < min_area:
            continue

        # bbox is (min_row, min_col, max_row, max_col)
        min_row, min_col, max_row, max_col = prop.bbox
        bbox_y = int(min_row)
        bbox_x = int(min_col)
        bbox_h = int(max_row - min_row)
        bbox_w = int(max_col - min_col)

        # Filter edge-touching ROIs
        if exclude_edge:
            if (min_row <= 0 or min_col <= 0
                    or max_row >= h or max_col >= w):
                continue

        results.append({
            "label_id": int(prop.label),
            "bbox_y": bbox_y,
            "bbox_x": bbox_x,
            "bbox_h": bbox_h,
            "bbox_w": bbox_w,
            "area_px": area,
        })

    return results


def filter_edge_rois(
    labels: np.ndarray,
    edge_margin: int = 0,
) -> tuple[np.ndarray, int]:
    """Remove ROIs whose bounding box is within *edge_margin* of the image border.

    Returns a new array; the input is not modified.

    Args:
        labels: 2D integer label image (0 = background).
        edge_margin: Pixels from border. 0 = only ROIs touching edge.

    Returns:
        Tuple of (filtered_labels, removed_count).
    """
    if labels.max() == 0:
        return labels.copy(), 0

    h, w = labels.shape
    edge_labels: list[int] = []
    for prop in regionprops(labels):
        min_row, min_col, max_row, max_col = prop.bbox
        if (min_row <= edge_margin or min_col <= edge_margin
                or max_row >= h - edge_margin or max_col >= w - edge_margin):
            edge_labels.append(prop.label)

    if not edge_labels:
        return labels.copy(), 0

    filtered = labels.copy()
    filtered[np.isin(filtered, edge_labels)] = 0
    return filtered, len(edge_labels)


def filter_small_rois(
    labels: np.ndarray,
    min_area: int,
) -> tuple[np.ndarray, int]:
    """Remove ROIs with area (in pixels) below *min_area*.

    Returns a new array; the input is not modified.

    Args:
        labels: 2D integer label image (0 = background).
        min_area: Minimum ROI area in pixels. ROIs smaller than this
            are zeroed out.

    Returns:
        Tuple of (filtered_labels, removed_count).
    """
    if labels.max() == 0:
        return labels.copy(), 0

    small_labels: list[int] = []
    for prop in regionprops(labels):
        if prop.area < min_area:
            small_labels.append(prop.label)

    if not small_labels:
        return labels.copy(), 0

    filtered = labels.copy()
    filtered[np.isin(filtered, small_labels)] = 0
    return filtered, len(small_labels)
