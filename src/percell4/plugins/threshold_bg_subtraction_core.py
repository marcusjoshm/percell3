"""Core math for threshold-based background subtraction.

Pure numpy module with no store dependencies. Estimates per-group background
from dilute-phase pixels (inside ROI bounding boxes but outside cell masks),
then builds a single derived image with per-cell background subtraction and
NaN outside all ROIs.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt


@dataclass(frozen=True, slots=True, kw_only=True)
class CellBGInfo:
    """Background info for a single cell.

    Attributes:
        label_id: Integer label in the label image.
        group_name: Name of the intensity group this cell belongs to.
        bg_value: Background value estimated for this cell's group.
        bbox: Bounding box (y, x, h, w) for this cell.
    """

    label_id: int
    group_name: str
    bg_value: float
    bbox: tuple[int, int, int, int]  # (y, x, h, w)


@dataclass(frozen=True, slots=True, kw_only=True)
class GroupBGResult:
    """Result of per-group background estimation.

    Attributes:
        group_name: Name of the intensity group.
        bg_value: Estimated background intensity.
        n_dilute_pixels: Number of dilute-phase pixels used for estimation.
    """

    group_name: str
    bg_value: float
    n_dilute_pixels: int


def estimate_group_background(
    image: npt.NDArray[np.number],
    label_image: npt.NDArray[np.integer],
    cell_label_ids: list[int],
    cell_bboxes: list[tuple[int, int, int, int]],
) -> float:
    """Estimate background from dilute-phase pixels for a group of cells.

    Dilute-phase pixels are those inside cell bounding boxes but outside
    the cell masks (i.e., the "background" around each cell). Background
    is estimated as the histogram mode of these pixels.

    Args:
        image: 2D intensity image.
        label_image: 2D integer label image where pixel value = cell label_id.
        cell_label_ids: Label IDs of cells in this group.
        cell_bboxes: Bounding boxes (y, x, h, w) for each cell.

    Returns:
        Estimated background value (histogram mode of dilute pixels).
    """
    from percell4.plugins.peak_detection import find_gaussian_peaks

    label_set = set(cell_label_ids)
    dilute_pixels: list[npt.NDArray] = []

    for label_id, (by, bx, bh, bw) in zip(cell_label_ids, cell_bboxes):
        # Extract bounding box region
        roi_image = image[by : by + bh, bx : bx + bw]
        roi_labels = label_image[by : by + bh, bx : bx + bw]

        # Dilute pixels: inside bbox but NOT belonging to any cell in the group
        outside_mask = ~np.isin(roi_labels, list(label_set))
        # Also exclude pixels belonging to label 0 (background in label image)
        # Actually we want dilute phase = inside bbox, outside any cell mask
        outside_cells = roi_labels == 0
        dilute_mask = outside_cells | outside_mask
        # Simplify: just use pixels where label == 0 (true background)
        dilute_mask = roi_labels == 0

        pixels = roi_image[dilute_mask]
        if len(pixels) > 0:
            dilute_pixels.append(pixels)

    if not dilute_pixels:
        return 0.0

    all_dilute = np.concatenate(dilute_pixels)
    if len(all_dilute) == 0:
        return 0.0

    # Use histogram peak detection (same as percell3)
    peak_result = find_gaussian_peaks(all_dilute)
    if peak_result is None:
        return float(np.median(all_dilute))

    return peak_result.background_value


def build_derived_image(
    image: npt.NDArray[np.number],
    label_image: npt.NDArray[np.integer],
    cell_bg_infos: list[CellBGInfo],
) -> npt.NDArray[np.float32]:
    """Build a background-subtracted image with NaN outside ROIs.

    For each cell, subtract its group's background value from the cell's
    pixels. All pixels outside any cell ROI are set to NaN.

    Args:
        image: 2D intensity image (any numeric dtype).
        label_image: 2D integer label image.
        cell_bg_infos: Background info for each cell.

    Returns:
        2D float32 image with BG-subtracted cell pixels, NaN elsewhere.
    """
    result = np.full(image.shape, float("nan"), dtype=np.float32)

    for info in cell_bg_infos:
        by, bx, bh, bw = info.bbox
        roi_labels = label_image[by : by + bh, bx : bx + bw]
        roi_image = image[by : by + bh, bx : bx + bw].astype(np.float32)

        cell_mask = roi_labels == info.label_id
        subtracted = np.clip(roi_image - info.bg_value, 0.0, None)

        # Write only this cell's pixels
        result_roi = result[by : by + bh, bx : bx + bw]
        result_roi[cell_mask] = subtracted[cell_mask]

    return result
