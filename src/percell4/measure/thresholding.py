"""ThresholdEngine — apply thresholding to produce binary masks.

Ported from percell3 with UUID IDs. Supports otsu, adaptive, manual,
triangle, and li methods.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from percell4.core.db_types import new_uuid, uuid_to_hex

if TYPE_CHECKING:
    from percell4.core.experiment_store import ExperimentStore

logger = logging.getLogger(__name__)

SUPPORTED_METHODS = frozenset({"otsu", "adaptive", "manual", "triangle", "li"})


def compute_threshold(image: np.ndarray, method: str = "otsu", **kwargs) -> float:
    """Compute a threshold value from an image.

    Args:
        image: 2D image array.
        method: Thresholding method ('otsu', 'manual', 'triangle', 'li').
        **kwargs: Additional arguments. ``manual_value`` required for 'manual'.

    Returns:
        The threshold value.

    Raises:
        ValueError: If method is unknown or manual_value missing.
    """
    from skimage.filters import threshold_li, threshold_otsu, threshold_triangle

    if method == "manual":
        manual_value = kwargs.get("manual_value")
        if manual_value is None:
            raise ValueError("manual_value is required when method='manual'")
        return float(manual_value)
    elif method == "otsu":
        return float(threshold_otsu(image))
    elif method == "triangle":
        return float(threshold_triangle(image))
    elif method == "li":
        return float(threshold_li(image))
    elif method == "adaptive":
        return float(threshold_otsu(image))
    else:
        raise ValueError(
            f"Unknown threshold method {method!r}. "
            f"Supported: {sorted(SUPPORTED_METHODS)}"
        )


@dataclass(frozen=True)
class ThresholdResult:
    """Result of a thresholding operation.

    Attributes:
        threshold_mask_id: UUID (bytes) of the threshold mask in the database.
        threshold_value: The computed (or manual) threshold value.
        positive_pixels: Number of pixels above the threshold.
        total_pixels: Total number of pixels in the image.
        positive_fraction: Fraction of pixels above the threshold.
    """

    threshold_mask_id: bytes
    threshold_value: float
    positive_pixels: int
    total_pixels: int
    positive_fraction: float


def create_threshold_mask(
    store: ExperimentStore,
    fov_id: bytes,
    source_channel_name: str,
    method: str = "otsu",
    grouping_channel_name: str | None = None,
    pipeline_run_id: bytes | None = None,
    **kwargs,
) -> ThresholdResult:
    """Create a threshold mask for a channel image.

    Reads the channel image, computes the threshold, creates the binary mask,
    writes it to LayerStore, and inserts a threshold_mask record in the DB.

    Args:
        store: Target ExperimentStore.
        fov_id: FOV database ID.
        source_channel_name: Channel name to threshold.
        method: Thresholding method.
        grouping_channel_name: Optional grouping channel name.
        pipeline_run_id: Pipeline run for provenance. Auto-created if None.
        **kwargs: Extra arguments (e.g., manual_value, gaussian_sigma).

    Returns:
        ThresholdResult with mask ID and statistics.
    """
    if method not in SUPPORTED_METHODS:
        raise ValueError(
            f"Unknown threshold method {method!r}. "
            f"Supported: {sorted(SUPPORTED_METHODS)}"
        )

    # Find channel index
    fov_row = store.db.get_fov(fov_id)
    channels = store.db.get_channels(fov_row["experiment_id"])
    channel_index = None
    for idx, ch in enumerate(channels):
        if ch["name"] == source_channel_name:
            channel_index = idx
            break
    if channel_index is None:
        raise ValueError(f"Channel {source_channel_name!r} not found")

    # Read image
    fov_hex = uuid_to_hex(fov_id)
    image = store.layers.read_image_channel_numpy(fov_hex, channel_index)

    # Apply Gaussian smoothing if requested
    gaussian_sigma = kwargs.get("gaussian_sigma")
    if gaussian_sigma and gaussian_sigma > 0:
        from scipy.ndimage import gaussian_filter
        image = gaussian_filter(image.astype(np.float32), sigma=gaussian_sigma)

    # Compute threshold
    threshold_value = compute_threshold(image, method, **kwargs)

    # Create binary mask
    if method == "adaptive":
        from skimage.filters import threshold_local
        block_size = max(15, (min(image.shape) // 10) | 1)
        local_thresh = threshold_local(image.astype(np.float64), block_size)
        mask = image > local_thresh
    else:
        mask = image > threshold_value

    # Create pipeline run if not provided
    if pipeline_run_id is None:
        pipeline_run_id = new_uuid()
        store.db.insert_pipeline_run(pipeline_run_id, "threshold")
        store.db.complete_pipeline_run(pipeline_run_id)

    # Write mask to LayerStore
    mask_id = new_uuid()
    mask_hex = uuid_to_hex(mask_id)
    zarr_path = store.layers.write_mask(mask_hex, mask.astype(np.uint8))

    # Insert threshold_mask record in DB
    store.db.insert_threshold_mask(
        id=mask_id,
        fov_id=fov_id,
        source_channel=source_channel_name,
        grouping_channel=grouping_channel_name,
        method=method,
        threshold_value=float(threshold_value),
        zarr_path=zarr_path,
        status="computed",
    )

    # Statistics
    positive_pixels = int(np.sum(mask))
    total_pixels = int(mask.size)
    positive_fraction = positive_pixels / total_pixels if total_pixels > 0 else 0.0

    return ThresholdResult(
        threshold_mask_id=mask_id,
        threshold_value=float(threshold_value),
        positive_pixels=positive_pixels,
        total_pixels=total_pixels,
        positive_fraction=positive_fraction,
    )
