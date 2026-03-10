"""CellGrouper — intensity-based ROI grouping using histogram binning.

Groups ROIs by measurement intensity into N bins, creating intensity_group
and cell_group_assignment records in the database.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from percell4.core.constants import SCOPE_WHOLE_ROI
from percell4.core.db_types import new_uuid, uuid_to_hex
from percell4.core.experiment_store import find_channel_index

if TYPE_CHECKING:
    from percell4.core.experiment_store import ExperimentStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GroupingResult:
    """Result of intensity-based ROI grouping.

    Attributes:
        n_groups: Number of groups created.
        group_ids: List of intensity_group UUIDs.
        group_boundaries: List of (lower, upper) bounds per group.
        rois_per_group: Count of ROIs in each group.
    """

    n_groups: int
    group_ids: list[bytes]
    group_boundaries: list[tuple[float, float]]
    rois_per_group: list[int]


def create_intensity_groups(
    store: ExperimentStore,
    fov_ids: list[bytes],
    channel_name: str,
    n_groups: int,
    pipeline_run_id: bytes,
) -> GroupingResult:
    """Group ROIs by intensity into N equal-width bins.

    Args:
        store: Target ExperimentStore.
        fov_ids: List of FOV IDs to include.
        channel_name: Channel name for grouping metric.
        n_groups: Number of intensity groups to create.
        pipeline_run_id: Pipeline run for provenance.

    Returns:
        GroupingResult with group IDs and boundaries.

    Raises:
        ValueError: If no measurements found or n_groups < 1.
    """
    if n_groups < 1:
        raise ValueError("n_groups must be >= 1")

    # Find channel ID from first FOV's experiment
    fov_row = store.db.get_fov(fov_ids[0])
    experiment_id = fov_row["experiment_id"]
    channels = store.db.get_channels(experiment_id)
    ch_idx = find_channel_index(channels, channel_name=channel_name)
    channel_id = channels[ch_idx]["id"]

    # Collect all ROI IDs and their mean_intensity measurements
    roi_values: list[tuple[bytes, float]] = []
    for fov_id in fov_ids:
        measurements = store.db.get_active_measurements(fov_id)
        for m in measurements:
            if (
                m["channel_id"] == channel_id
                and m["metric"] == "mean_intensity"
                and m["scope"] == SCOPE_WHOLE_ROI
            ):
                roi_values.append((m["roi_id"], m["value"]))

    if not roi_values:
        raise ValueError(
            f"No mean_intensity measurements found for channel "
            f"{channel_name!r} across {len(fov_ids)} FOVs"
        )

    roi_ids, values = zip(*roi_values)
    values_arr = np.array(values, dtype=np.float64)

    # Compute equal-width bin boundaries
    vmin = float(np.min(values_arr))
    vmax = float(np.max(values_arr))

    # Handle edge case: all values identical
    if vmax == vmin:
        boundaries = [(vmin, vmax)]
        n_groups = 1
    else:
        edges = np.linspace(vmin, vmax, n_groups + 1)
        boundaries = [
            (float(edges[i]), float(edges[i + 1]))
            for i in range(n_groups)
        ]

    # Assign ROIs to groups
    group_ids: list[bytes] = []
    rois_per_group: list[int] = []

    for gi, (lower, upper) in enumerate(boundaries):
        group_id = new_uuid()
        group_name = f"{channel_name}_g{gi + 1}"
        store.db.insert_intensity_group(
            id=group_id,
            experiment_id=experiment_id,
            name=group_name,
            channel_id=channel_id,
            pipeline_run_id=pipeline_run_id,
            group_index=gi,
            lower_bound=lower,
            upper_bound=upper,
        )
        group_ids.append(group_id)

        # Assign ROIs in this bin
        count = 0
        for roi_id, val in zip(roi_ids, values_arr):
            in_group = False
            if gi < len(boundaries) - 1:
                in_group = lower <= val < upper
            else:
                # Last group includes upper bound
                in_group = lower <= val <= upper

            if in_group:
                store.db.insert_cell_group_assignment(
                    id=new_uuid(),
                    intensity_group_id=group_id,
                    roi_id=roi_id,
                    pipeline_run_id=pipeline_run_id,
                )
                count += 1
        rois_per_group.append(count)

    return GroupingResult(
        n_groups=len(group_ids),
        group_ids=group_ids,
        group_boundaries=boundaries,
        rois_per_group=rois_per_group,
    )
