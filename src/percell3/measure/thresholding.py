"""ThresholdEngine — apply thresholding to produce binary masks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from percell3.core import ExperimentStore

SUPPORTED_METHODS = frozenset({"otsu", "adaptive", "manual", "triangle", "li"})


@dataclass(frozen=True)
class ThresholdResult:
    """Result of a thresholding operation.

    Attributes:
        threshold_run_id: ID of the threshold run in the database.
        threshold_value: The computed (or manual) threshold value.
        positive_pixels: Number of pixels above the threshold.
        total_pixels: Total number of pixels in the image.
        positive_fraction: Fraction of pixels above the threshold.
    """

    threshold_run_id: int
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
        fov: str,
        condition: str,
        channel: str,
        method: str = "otsu",
        manual_value: float | None = None,
        bio_rep: str | None = None,
        timepoint: str | None = None,
    ) -> ThresholdResult:
        """Apply thresholding to a channel image in a FOV.

        Args:
            store: Target ExperimentStore.
            fov: FOV name.
            condition: Condition name.
            channel: Channel name to threshold.
            method: Thresholding method ("otsu", "adaptive", "manual", "triangle", "li").
            manual_value: Threshold value (required when method="manual").
            bio_rep: Biological replicate name (auto-resolved if None).
            timepoint: Timepoint (optional).

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
        image = store.read_image_numpy(fov, condition, channel, bio_rep=bio_rep, timepoint=timepoint)

        # Compute threshold
        threshold_value = self._compute_threshold(image, method, manual_value)

        # Create binary mask
        if method == "adaptive":
            mask = self._adaptive_threshold(image)
        else:
            mask = image > threshold_value

        # Record threshold run
        parameters = {"method": method, "threshold_value": float(threshold_value)}
        if manual_value is not None:
            parameters["manual_value"] = float(manual_value)
        run_id = store.add_threshold_run(channel, method, parameters)

        # Write mask to masks.zarr
        store.write_mask(fov, condition, channel, mask.astype(np.uint8), run_id, bio_rep=bio_rep, timepoint=timepoint)

        # Statistics
        positive_pixels = int(np.sum(mask))
        total_pixels = int(mask.size)
        positive_fraction = positive_pixels / total_pixels if total_pixels > 0 else 0.0

        return ThresholdResult(
            threshold_run_id=run_id,
            threshold_value=float(threshold_value),
            positive_pixels=positive_pixels,
            total_pixels=total_pixels,
            positive_fraction=positive_fraction,
        )

    def threshold_group(
        self,
        store: ExperimentStore,
        fov: str,
        condition: str,
        channel: str,
        cell_ids: list[int],
        labels: np.ndarray,
        image: np.ndarray,
        threshold_value: float,
        roi: list[tuple[int, int, int, int]] | None = None,
        group_tag: str | None = None,
        bio_rep: str | None = None,
        timepoint: str | None = None,
    ) -> ThresholdResult:
        """Store a threshold result for a group of cells.

        Creates a binary mask by applying the threshold to the group image
        (image with non-group cells zeroed), records the threshold run,
        and writes the mask to zarr.

        Args:
            store: Target ExperimentStore.
            fov: FOV name.
            condition: Condition name.
            channel: Channel name that was thresholded.
            cell_ids: Cell IDs in this group.
            labels: 2D label image (full FOV).
            image: 2D channel image (full FOV).
            threshold_value: Otsu (or manually adjusted) threshold value.
            roi: Optional ROI rectangles used for Otsu computation.
            group_tag: Tag name for this group (stored in parameters).
            bio_rep: Biological replicate name.
            timepoint: Timepoint.

        Returns:
            ThresholdResult with run ID and statistics.
        """
        from percell3.measure.threshold_viewer import create_group_image

        # Get label values for the group cells
        cells_df = store.get_cells(condition=condition, bio_rep=bio_rep, fov=fov)
        group_cells = cells_df[cells_df["id"].isin(cell_ids)]
        label_values = group_cells["label_value"].tolist()

        group_image, cell_mask = create_group_image(image, labels, label_values)

        # Create binary mask: threshold applied to full group image (not just ROI)
        mask = (group_image > threshold_value) & cell_mask

        # Record threshold run with parameters
        parameters = {
            "method": "otsu",
            "threshold_value": float(threshold_value),
            "fov_name": fov,
            "condition": condition,
        }
        if roi:
            parameters["roi"] = [list(r) for r in roi]
        if group_tag:
            parameters["group_tag"] = group_tag

        run_id = store.add_threshold_run(channel, "otsu", parameters)

        # Write mask
        store.write_mask(
            fov, condition, channel, mask.astype(np.uint8),
            run_id, bio_rep=bio_rep, timepoint=timepoint,
        )

        # Statistics
        positive_pixels = int(np.sum(mask))
        total_pixels = int(np.sum(cell_mask))
        positive_fraction = positive_pixels / total_pixels if total_pixels > 0 else 0.0

        return ThresholdResult(
            threshold_run_id=run_id,
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
