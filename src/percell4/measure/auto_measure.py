"""Auto-measurement pipeline — wire to MeasurementNeeded pattern.

Consumes MeasurementNeeded items emitted by assignment changes and
dispatches measurement jobs to the Measurer.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from percell4.core.constants import SCOPE_MASK_INSIDE, SCOPE_MASK_OUTSIDE
from percell4.core.db_types import uuid_to_hex
from percell4.measure.measurer import Measurer

if TYPE_CHECKING:
    from percell4.core.experiment_store import ExperimentStore
    from percell4.core.models import MeasurementNeeded

logger = logging.getLogger(__name__)


def run_measurements(
    store: ExperimentStore,
    needed: list[MeasurementNeeded],
    on_progress: Callable[[int, int], None] | None = None,
) -> int:
    """Execute measurements for a list of MeasurementNeeded work items.

    For each item:
      1. Find the active segmentation assignment for this FOV + roi_type.
      2. Get seg_set_id from the assignment.
      3. For each channel_id, call measure_fov_whole().
      4. Check for active mask assignments and measure masked scopes
         if present.

    Args:
        store: Target ExperimentStore.
        needed: List of MeasurementNeeded items describing what to measure.
        on_progress: Optional callback(current, total) for progress.

    Returns:
        Total number of measurements created.
    """
    measurer = Measurer()
    total = 0
    count = len(needed)

    for idx, item in enumerate(needed):
        try:
            # Get active segmentation assignment for this FOV + roi_type
            assignments = store.get_active_assignments(item.fov_id)
            seg_assignments = assignments["segmentation"]

            # Find assignment matching our roi_type
            seg_set_id = None
            pipeline_run_id = None
            for sa in seg_assignments:
                if sa["roi_type_id"] == item.roi_type_id:
                    seg_set_id = sa["segmentation_set_id"]
                    pipeline_run_id = sa["pipeline_run_id"]
                    break

            if seg_set_id is None:
                logger.warning(
                    "No active segmentation assignment for FOV %s, roi_type — skipping",
                    uuid_to_hex(item.fov_id),
                )
                continue

            # Measure whole_roi for each channel
            for channel_id in item.channel_ids:
                try:
                    n = measurer.measure_fov_whole(
                        store,
                        fov_id=item.fov_id,
                        channel_id=channel_id,
                        seg_set_id=seg_set_id,
                        roi_type_id=item.roi_type_id,
                        pipeline_run_id=pipeline_run_id,
                    )
                    total += n
                except Exception:
                    logger.exception(
                        "Whole-ROI measurement failed for fov=%s, channel=%s",
                        uuid_to_hex(item.fov_id),
                        uuid_to_hex(channel_id),
                    )

            # Check for active mask assignments and measure masked scopes
            mask_assignments = assignments["mask"]
            for ma in mask_assignments:
                if ma["purpose"] != "measurement_scope":
                    continue
                mask_pipeline_run_id = ma["pipeline_run_id"]
                for channel_id in item.channel_ids:
                    try:
                        n = measurer.measure_fov_masked(
                            store,
                            fov_id=item.fov_id,
                            channel_id=channel_id,
                            seg_set_id=seg_set_id,
                            roi_type_id=item.roi_type_id,
                            mask_id=ma["threshold_mask_id"],
                            scopes=[SCOPE_MASK_INSIDE, SCOPE_MASK_OUTSIDE],
                            pipeline_run_id=mask_pipeline_run_id,
                        )
                        total += n
                    except Exception:
                        logger.exception(
                            "Masked measurement failed for fov=%s, mask=%s",
                            uuid_to_hex(item.fov_id),
                            uuid_to_hex(ma["threshold_mask_id"]),
                        )

        except Exception:
            logger.exception(
                "Measurement dispatch failed for fov=%s",
                uuid_to_hex(item.fov_id),
            )

        if on_progress:
            on_progress(idx + 1, count)

    return total
