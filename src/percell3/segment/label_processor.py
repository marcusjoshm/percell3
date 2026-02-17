"""Label image to CellRecord extraction using scikit-image regionprops."""

from __future__ import annotations

import math

import numpy as np
from skimage.measure import regionprops

from percell3.core.models import CellRecord


def extract_cells(
    labels: np.ndarray,
    fov_id: int,
    segmentation_id: int,
    pixel_size_um: float | None = None,
) -> list[CellRecord]:
    """Convert a label image to a list of CellRecord objects.

    Args:
        labels: 2D integer array (Y, X) where pixel value = cell ID,
            0 = background.
        fov_id: Database ID of the FOV this label image belongs to.
        segmentation_id: Database ID of the segmentation run.
        pixel_size_um: Physical pixel size in micrometers. If provided,
            ``area_um2`` is computed. Otherwise it is set to None.

    Returns:
        List of CellRecord objects, one per labeled region.
        Empty list if the label image contains no cells.
    """
    if labels.max() == 0:
        return []

    props = regionprops(labels)
    cells: list[CellRecord] = []

    for prop in props:
        # regionprops returns centroid as (row, col) = (y, x) — must swap
        centroid_y_raw, centroid_x_raw = prop.centroid
        centroid_x = float(centroid_x_raw)
        centroid_y = float(centroid_y_raw)

        # bbox is (min_row, min_col, max_row, max_col)
        min_row, min_col, max_row, max_col = prop.bbox
        bbox_x = int(min_col)
        bbox_y = int(min_row)
        bbox_w = int(max_col - min_col)
        bbox_h = int(max_row - min_row)

        area_pixels = float(prop.area)

        area_um2: float | None = None
        if pixel_size_um is not None:
            area_um2 = area_pixels * pixel_size_um ** 2

        perimeter = float(prop.perimeter)

        # Circularity: 4 * pi * area / perimeter^2
        if perimeter > 0:
            circularity = 4.0 * math.pi * area_pixels / perimeter ** 2
        else:
            circularity = 0.0

        cells.append(
            CellRecord(
                fov_id=fov_id,
                segmentation_id=segmentation_id,
                label_value=int(prop.label),
                centroid_x=centroid_x,
                centroid_y=centroid_y,
                bbox_x=bbox_x,
                bbox_y=bbox_y,
                bbox_w=bbox_w,
                bbox_h=bbox_h,
                area_pixels=area_pixels,
                area_um2=area_um2,
                perimeter=perimeter,
                circularity=circularity,
            )
        )

    return cells


class LabelProcessor:
    """Extract cell properties from a label image.

    Uses ``skimage.measure.regionprops`` to compute centroid, bounding box,
    area, perimeter, and circularity for each labeled region.

    .. deprecated::
        Use the module-level ``extract_cells()`` function directly.
    """

    def extract_cells(
        self,
        labels: np.ndarray,
        fov_id: int,
        segmentation_id: int,
        pixel_size_um: float | None = None,
    ) -> list[CellRecord]:
        """Convert a label image to a list of CellRecord objects."""
        return extract_cells(labels, fov_id, segmentation_id, pixel_size_um)
