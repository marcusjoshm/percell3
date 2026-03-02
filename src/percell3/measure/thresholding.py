"""ThresholdEngine — apply thresholding to produce binary masks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from percell3.core import ExperimentStore

SUPPORTED_METHODS = frozenset({"otsu", "adaptive", "manual", "triangle", "li"})


def apply_gaussian_smoothing(
    image: np.ndarray, sigma: float | None,
) -> np.ndarray:
    """Apply Gaussian smoothing if sigma is set.

    Args:
        image: 2D image array.
        sigma: Gaussian sigma. None or <= 0 means no smoothing.

    Returns:
        Smoothed image (float32) or the original image unchanged.
    """
    if sigma is None or sigma <= 0:
        return image
    from scipy.ndimage import gaussian_filter

    return gaussian_filter(image.astype(np.float32), sigma=sigma)


@dataclass(frozen=True)
class ThresholdResult:
    """Result of a thresholding operation.

    Attributes:
        threshold_id: ID of the threshold entity in the database.
        threshold_value: The computed (or manual) threshold value.
        positive_pixels: Number of pixels above the threshold.
        total_pixels: Total number of pixels in the image.
        positive_fraction: Fraction of pixels above the threshold.
    """

    threshold_id: int
    threshold_value: float
    positive_pixels: int
    total_pixels: int
    positive_fraction: float


class ThresholdEngine:
    """Apply thresholding methods to channel images and store binary masks.

    Supported methods: otsu, adaptive, manual, triangle, li.
    """

    def threshold_fov(
        self,
        store: ExperimentStore,
        fov_id: int,
        channel: str,
        method: str = "otsu",
        manual_value: float | None = None,
        gaussian_sigma: float | None = None,
    ) -> ThresholdResult:
        """Apply thresholding to a channel image in a FOV.

        Creates a global threshold entity, writes the binary mask,
        and triggers auto-measurement.

        Args:
            store: Target ExperimentStore.
            fov_id: FOV database ID.
            channel: Channel name to threshold.
            method: Thresholding method ("otsu", "adaptive", "manual", "triangle", "li").
            manual_value: Threshold value (required when method="manual").
            gaussian_sigma: Optional Gaussian smoothing sigma.

        Returns:
            ThresholdResult with threshold value and statistics.

        Raises:
            ValueError: If method is unknown or manual_value missing for manual method.
        """
        if method not in SUPPORTED_METHODS:
            raise ValueError(
                f"Unknown threshold method {method!r}. "
                f"Supported: {sorted(SUPPORTED_METHODS)}"
            )
        if method == "manual" and manual_value is None:
            raise ValueError("manual_value is required when method='manual'")

        # Read channel image
        image = store.read_image_numpy(fov_id, channel)

        # Apply Gaussian smoothing if requested
        image = apply_gaussian_smoothing(image, gaussian_sigma)

        # Compute threshold
        threshold_value = self._compute_threshold(image, method, manual_value)

        # Create binary mask
        if method == "adaptive":
            mask = self._adaptive_threshold(image)
        else:
            mask = image > threshold_value

        h, w = mask.shape

        # Record threshold as global entity
        parameters = {"method": method, "threshold_value": float(threshold_value)}
        if manual_value is not None:
            parameters["manual_value"] = float(manual_value)
        if gaussian_sigma is not None and gaussian_sigma > 0:
            parameters["gaussian_sigma"] = float(gaussian_sigma)

        name = store._generate_threshold_name(channel, channel)
        thr_id = store.add_threshold(
            name=name, method=method,
            width=w, height=h,
            source_fov_id=fov_id, source_channel=channel,
            parameters=parameters,
        )
        store.update_threshold_value(thr_id, float(threshold_value))

        # Write mask to masks.zarr
        store.write_mask(mask.astype(np.uint8), thr_id)

        # Statistics
        positive_pixels = int(np.sum(mask))
        total_pixels = int(mask.size)
        positive_fraction = positive_pixels / total_pixels if total_pixels > 0 else 0.0

        return ThresholdResult(
            threshold_id=thr_id,
            threshold_value=float(threshold_value),
            positive_pixels=positive_pixels,
            total_pixels=total_pixels,
            positive_fraction=positive_fraction,
        )

    def threshold_group(
        self,
        store: ExperimentStore,
        fov_id: int,
        channel: str,
        cell_ids: list[int],
        labels: np.ndarray,
        image: np.ndarray,
        threshold_value: float,
        roi: list[tuple[int, int, int, int]] | None = None,
        group_tag: str | None = None,
        gaussian_sigma: float | None = None,
    ) -> ThresholdResult:
        """Store a threshold result for a group of cells.

        Creates a global threshold entity with a binary mask by applying
        the threshold to the group image (image with non-group cells zeroed).

        Args:
            store: Target ExperimentStore.
            fov_id: FOV database ID.
            channel: Channel name that was thresholded.
            cell_ids: Cell IDs in this group.
            labels: 2D label image (full FOV).
            image: 2D channel image (full FOV).
            threshold_value: Otsu (or manually adjusted) threshold value.
            roi: Optional ROI rectangles used for Otsu computation.
            group_tag: Tag name for this group (stored in parameters).
            gaussian_sigma: Optional Gaussian smoothing sigma.

        Returns:
            ThresholdResult with threshold entity ID and statistics.
        """
        from percell3.measure.threshold_viewer import create_group_image

        # Get label values for the group cells
        cells_df = store.get_cells(fov_id=fov_id)
        group_cells = cells_df[cells_df["id"].isin(cell_ids)]
        label_values = group_cells["label_value"].tolist()

        group_image, cell_mask = create_group_image(image, labels, label_values)

        # Apply Gaussian smoothing if requested
        group_image = apply_gaussian_smoothing(group_image, gaussian_sigma)

        # Create binary mask: threshold applied to full group image (not just ROI)
        mask = (group_image > threshold_value) & cell_mask

        h, w = mask.shape

        # Record threshold as global entity
        fov_info = store.get_fov_by_id(fov_id)
        parameters = {
            "method": "otsu",
            "threshold_value": float(threshold_value),
            "fov_name": fov_info.display_name,
            "condition": fov_info.condition,
        }
        if roi:
            parameters["roi"] = [list(r) for r in roi]
        if group_tag:
            parameters["group_tag"] = group_tag
        if gaussian_sigma is not None and gaussian_sigma > 0:
            parameters["gaussian_sigma"] = float(gaussian_sigma)

        grouping_ch = group_tag or ""
        name = store._generate_threshold_name(grouping_ch, channel)
        thr_id = store.add_threshold(
            name=name, method="otsu",
            width=w, height=h,
            source_fov_id=fov_id, source_channel=channel,
            grouping_channel=grouping_ch or None,
            parameters=parameters,
        )
        store.update_threshold_value(thr_id, float(threshold_value))

        # Write mask
        store.write_mask(mask.astype(np.uint8), thr_id)

        # Statistics
        positive_pixels = int(np.sum(mask))
        total_pixels = int(np.sum(cell_mask))
        positive_fraction = positive_pixels / total_pixels if total_pixels > 0 else 0.0

        return ThresholdResult(
            threshold_id=thr_id,
            threshold_value=float(threshold_value),
            positive_pixels=positive_pixels,
            total_pixels=total_pixels,
            positive_fraction=positive_fraction,
        )

    def _compute_threshold(
        self,
        image: np.ndarray,
        method: str,
        manual_value: float | None,
    ) -> float:
        """Compute the threshold value using the specified method."""
        from skimage.filters import (
            threshold_li,
            threshold_otsu,
            threshold_triangle,
        )

        if method == "manual":
            return float(manual_value)
        elif method == "otsu":
            return float(threshold_otsu(image))
        elif method == "triangle":
            return float(threshold_triangle(image))
        elif method == "li":
            return float(threshold_li(image))
        elif method == "adaptive":
            # For adaptive, we still return the global otsu as reference
            return float(threshold_otsu(image))
        else:
            raise ValueError(f"Unknown method: {method}")

    def _adaptive_threshold(self, image: np.ndarray) -> np.ndarray:
        """Apply adaptive (local) thresholding."""
        from skimage.filters import threshold_local

        # Block size must be odd; use ~1/10 of image dimension, min 15
        block_size = max(15, (min(image.shape) // 10) | 1)
        local_thresh = threshold_local(image.astype(np.float64), block_size)
        return image > local_thresh
