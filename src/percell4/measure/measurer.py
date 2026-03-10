"""Measurer — per-FOV measurement engine using labels and channel images.

Ported from percell3 with UUID IDs and unified ROI terminology.
All entity IDs are ``bytes`` (16-byte UUIDs).  "cell" is now "ROI"
everywhere except user-facing display.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

from percell4.core.constants import SCOPE_MASK_INSIDE, SCOPE_MASK_OUTSIDE, SCOPE_WHOLE_ROI
from percell4.core.db_types import new_uuid
from percell4.core.experiment_store import find_channel_index
from percell4.measure.metrics import METRIC_FUNCTIONS, MetricRegistry

if TYPE_CHECKING:
    from percell4.core.experiment_store import ExperimentStore

logger = logging.getLogger(__name__)


def measure_roi(
    image: np.ndarray,
    mask: np.ndarray,
    bbox: tuple[int, int, int, int],
) -> dict[str, float]:
    """Measure all 7 metrics for a single ROI using bbox optimisation.

    Args:
        image: Full FOV channel image (2D).
        mask: Full FOV boolean mask (True where the ROI is) or label-derived.
        bbox: Bounding box as (bbox_y, bbox_x, bbox_h, bbox_w).

    Returns:
        Dict mapping metric name to scalar value.
    """
    by, bx, bh, bw = bbox
    image_crop = image[by : by + bh, bx : bx + bw]
    mask_crop = mask[by : by + bh, bx : bx + bw]

    if not np.any(mask_crop):
        return {name: 0.0 for name in METRIC_FUNCTIONS}

    return {
        name: func(image_crop, mask_crop)
        for name, func in METRIC_FUNCTIONS.items()
    }


class Measurer:
    """Compute per-ROI measurements by combining labels with channel images.

    Uses bounding-box optimisation: for each ROI, crops both the label
    image and channel image to the ROI's bounding box before computing
    metrics.

    Args:
        metrics: Optional MetricRegistry. If None, uses default builtins.
    """

    def __init__(self, metrics: MetricRegistry | None = None) -> None:
        self._metrics = metrics or MetricRegistry()

    def measure_fov_whole(
        self,
        store: ExperimentStore,
        fov_id: bytes,
        channel_id: bytes,
        seg_set_id: bytes,
        roi_type_id: bytes,
        pipeline_run_id: bytes,
        metrics: list[str] | None = None,
    ) -> int:
        """Measure all ROIs in a FOV on one channel with whole_roi scope.

        Args:
            store: Target ExperimentStore.
            fov_id: FOV database ID (UUID bytes).
            channel_id: Channel database ID (UUID bytes).
            seg_set_id: Segmentation set whose labels to read.
            roi_type_id: ROI type to measure.
            pipeline_run_id: Pipeline run for provenance.
            metrics: Metric names (default: all registered metrics).

        Returns:
            Number of measurements written.
        """
        from percell4.core.db_types import uuid_to_hex

        metric_names = metrics or self._metrics.list_metrics()

        # Get ROIs for this FOV + type
        rois = store.db.get_rois_by_fov_and_type(fov_id, roi_type_id)
        if not rois:
            logger.info("No ROIs for fov+type — skipping")
            return 0

        # Read image and labels via LayerStore
        fov_hex = uuid_to_hex(fov_id)
        seg_hex = uuid_to_hex(seg_set_id)

        # Find channel index from experiment channels
        fov_row = store.db.get_fov(fov_id)
        channels = store.db.get_channels(fov_row["experiment_id"])
        channel_index = find_channel_index(channels, channel_id=channel_id)

        image = store.layers.read_image_channel_numpy(fov_hex, channel_index)
        labels = store.layers.read_labels(seg_hex, fov_hex)

        bulk_rows: list[tuple] = []
        for roi in rois:
            label_val = roi["label_id"]
            by = roi["bbox_y"]
            bx = roi["bbox_x"]
            bh = roi["bbox_h"]
            bw = roi["bbox_w"]

            label_crop = labels[by : by + bh, bx : bx + bw]
            image_crop = image[by : by + bh, bx : bx + bw]
            roi_mask = label_crop == label_val

            if not np.any(roi_mask):
                continue

            for metric_name in metric_names:
                value = self._metrics.compute(metric_name, image_crop, roi_mask)
                bulk_rows.append((
                    new_uuid(),
                    roi["id"],
                    channel_id,
                    metric_name,
                    SCOPE_WHOLE_ROI,
                    value,
                    pipeline_run_id,
                ))

        if bulk_rows:
            store.db.add_measurements_bulk(bulk_rows)

        return len(bulk_rows)

    def measure_fov_masked(
        self,
        store: ExperimentStore,
        fov_id: bytes,
        channel_id: bytes,
        seg_set_id: bytes,
        roi_type_id: bytes,
        mask_id: bytes,
        scopes: list[str],
        pipeline_run_id: bytes,
        metrics: list[str] | None = None,
    ) -> int:
        """Measure ROIs using a threshold mask to define inside/outside regions.

        For each ROI, the threshold mask is cropped to the ROI's bounding box.
        ``mask_inside`` measures pixels where both the ROI mask and threshold
        mask are True. ``mask_outside`` measures pixels where the ROI mask is
        True but the threshold mask is False.

        Args:
            store: Target ExperimentStore.
            fov_id: FOV database ID.
            channel_id: Channel database ID.
            seg_set_id: Segmentation set whose labels to read.
            roi_type_id: ROI type to measure.
            mask_id: Threshold mask ID.
            scopes: Subset of ['mask_inside', 'mask_outside'].
            pipeline_run_id: Pipeline run for provenance.
            metrics: Metric names (default: all registered metrics).

        Returns:
            Number of measurements written.
        """
        from percell4.core.db_types import uuid_to_hex

        metric_names = metrics or self._metrics.list_metrics()
        valid_scopes = {SCOPE_MASK_INSIDE, SCOPE_MASK_OUTSIDE}
        for s in scopes:
            if s not in valid_scopes:
                raise ValueError(
                    f"Invalid scope {s!r}, must be one of {valid_scopes}"
                )

        rois = store.db.get_rois_by_fov_and_type(fov_id, roi_type_id)
        if not rois:
            logger.info("No ROIs for fov+type — skipping masked measurement")
            return 0

        fov_hex = uuid_to_hex(fov_id)
        seg_hex = uuid_to_hex(seg_set_id)
        mask_hex = uuid_to_hex(mask_id)

        # Find channel index
        fov_row = store.db.get_fov(fov_id)
        channels = store.db.get_channels(fov_row["experiment_id"])
        channel_index = find_channel_index(channels, channel_id=channel_id)

        image = store.layers.read_image_channel_numpy(fov_hex, channel_index)
        labels = store.layers.read_labels(seg_hex, fov_hex)
        thresh_mask = store.layers.read_mask(mask_hex)
        thresh_bool = thresh_mask > 0

        bulk_rows: list[tuple] = []
        for roi in rois:
            label_val = roi["label_id"]
            by = roi["bbox_y"]
            bx = roi["bbox_x"]
            bh = roi["bbox_h"]
            bw = roi["bbox_w"]

            label_crop = labels[by : by + bh, bx : bx + bw]
            image_crop = image[by : by + bh, bx : bx + bw]
            thresh_crop = thresh_bool[by : by + bh, bx : bx + bw]
            roi_mask = label_crop == label_val

            if not np.any(roi_mask):
                continue

            for scope in scopes:
                if scope == SCOPE_MASK_INSIDE:
                    scoped_mask = roi_mask & thresh_crop
                else:
                    scoped_mask = roi_mask & ~thresh_crop

                has_pixels = np.any(scoped_mask)

                for metric_name in metric_names:
                    if has_pixels:
                        value = self._metrics.compute(
                            metric_name, image_crop, scoped_mask,
                        )
                    else:
                        value = 0.0
                    bulk_rows.append((
                        new_uuid(),
                        roi["id"],
                        channel_id,
                        metric_name,
                        scope,
                        value,
                        pipeline_run_id,
                    ))

        if bulk_rows:
            store.db.add_measurements_bulk(bulk_rows)

        return len(bulk_rows)
