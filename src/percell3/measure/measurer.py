"""Measurer — per-FOV measurement engine using labels and channel images."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

from percell3.core.models import MeasurementRecord
from percell3.measure.metrics import MetricRegistry

if TYPE_CHECKING:
    from percell3.core import ExperimentStore

logger = logging.getLogger(__name__)


class Measurer:
    """Compute per-cell measurements by combining labels with channel images.

    Uses bounding-box optimization: for each cell, crops both the label
    image and channel image to the cell's bounding box before computing
    metrics.

    Args:
        metrics: Optional MetricRegistry. If None, uses default builtins.
    """

    def __init__(self, metrics: MetricRegistry | None = None) -> None:
        self._metrics = metrics or MetricRegistry()

    def measure_fov(
        self,
        store: ExperimentStore,
        fov: str,
        condition: str,
        channels: list[str],
        metrics: list[str] | None = None,
        segmentation_run_id: int | None = None,
        timepoint: str | None = None,
    ) -> int:
        """Measure all cells in a FOV across specified channels.

        Args:
            store: Target ExperimentStore.
            fov: FOV name.
            condition: Condition name.
            channels: Channel names to measure.
            metrics: Metric names (default: all registered metrics).
            segmentation_run_id: Which segmentation to use (default: latest).
            timepoint: Timepoint (optional).

        Returns:
            Number of measurements written.

        Raises:
            ValueError: If no cells found or channel doesn't exist.
        """
        metric_names = metrics or self._metrics.list_metrics()
        for m in metric_names:
            if m not in self._metrics:
                raise KeyError(f"Unknown metric {m!r}")

        # Get cells for this FOV
        cells_df = store.get_cells(
            condition=condition, fov=fov, timepoint=timepoint,
        )
        if cells_df.empty:
            logger.info("No cells found in %s/%s — skipping", condition, fov)
            return 0

        # Filter by segmentation run if specified
        if segmentation_run_id is not None:
            cells_df = cells_df[cells_df["segmentation_id"] == segmentation_run_id]
            if cells_df.empty:
                return 0

        # Read label image once
        labels = store.read_labels(fov, condition, timepoint)

        all_records: list[MeasurementRecord] = []

        for channel in channels:
            ch_info = store.get_channel(channel)
            image = store.read_image_numpy(fov, condition, channel, timepoint)

            records = self._measure_cells_on_channel(
                cells_df, labels, image, ch_info.id, metric_names,
            )
            all_records.extend(records)

        if all_records:
            store.add_measurements(all_records)

        return len(all_records)

    def measure_cells(
        self,
        store: ExperimentStore,
        cell_ids: list[int],
        fov: str,
        condition: str,
        channel: str,
        metrics: list[str] | None = None,
        timepoint: str | None = None,
    ) -> list[MeasurementRecord]:
        """Measure specific cells on a specific channel (preview, no DB write).

        Args:
            store: Target ExperimentStore.
            cell_ids: Cell IDs to measure.
            fov: FOV name.
            condition: Condition name.
            channel: Channel name.
            metrics: Metric names (default: all).
            timepoint: Timepoint (optional).

        Returns:
            List of MeasurementRecords (not written to DB).
        """
        metric_names = metrics or self._metrics.list_metrics()

        cells_df = store.get_cells(condition=condition, fov=fov, timepoint=timepoint)
        if cells_df.empty:
            return []

        cells_df = cells_df[cells_df["id"].isin(cell_ids)]
        if cells_df.empty:
            return []

        labels = store.read_labels(fov, condition, timepoint)
        ch_info = store.get_channel(channel)
        image = store.read_image_numpy(fov, condition, channel, timepoint)

        return self._measure_cells_on_channel(
            cells_df, labels, image, ch_info.id, metric_names,
        )

    def _measure_cells_on_channel(
        self,
        cells_df,
        labels: np.ndarray,
        image: np.ndarray,
        channel_id: int,
        metric_names: list[str],
    ) -> list[MeasurementRecord]:
        """Measure all cells on one channel using bbox optimization.

        For each cell, crops to the bounding box to avoid processing the
        full image per cell.
        """
        records: list[MeasurementRecord] = []

        for _, cell in cells_df.iterrows():
            cell_id = int(cell["id"])
            label_val = int(cell["label_value"])
            bx = int(cell["bbox_x"])
            by = int(cell["bbox_y"])
            bw = int(cell["bbox_w"])
            bh = int(cell["bbox_h"])

            # Crop to bounding box
            label_crop = labels[by : by + bh, bx : bx + bw]
            image_crop = image[by : by + bh, bx : bx + bw]

            # Create binary mask for this cell
            cell_mask = label_crop == label_val

            if not np.any(cell_mask):
                continue

            # Compute each metric
            for metric_name in metric_names:
                value = self._metrics.compute(metric_name, image_crop, cell_mask)
                records.append(MeasurementRecord(
                    cell_id=cell_id,
                    channel_id=channel_id,
                    metric=metric_name,
                    value=value,
                ))

        return records
