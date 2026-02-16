"""SegmentationEngine — pipeline orchestration for segmentation runs."""

from __future__ import annotations

import time
from typing import Callable

from percell3.core import ExperimentStore
from percell3.core.exceptions import ChannelNotFoundError
from percell3.segment.base_segmenter import (
    BaseSegmenter,
    SegmentationParams,
    SegmentationResult,
)
from percell3.segment.label_processor import LabelProcessor


class SegmentationEngine:
    """Orchestrates a full segmentation run across experiment regions.

    Reads images from ExperimentStore, runs segmentation via a
    ``BaseSegmenter`` backend, writes label images to ``labels.zarr``,
    and populates the ``cells`` table with extracted cell properties.

    Args:
        segmenter: Segmentation backend. If None, a ``CellposeAdapter``
            is lazily created on first call to ``run()``.
    """

    def __init__(self, segmenter: BaseSegmenter | None = None) -> None:
        self._segmenter = segmenter

    def run(
        self,
        store: ExperimentStore,
        channel: str = "DAPI",
        model: str = "cyto3",
        diameter: int | float | None = None,
        regions: list[str] | None = None,
        condition: str | None = None,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> SegmentationResult:
        """Run segmentation on experiment regions.

        Args:
            store: Target ExperimentStore.
            channel: Channel name to segment.
            model: Cellpose model name (e.g., "cyto3", "nuclei").
            diameter: Expected cell diameter in pixels. None = auto-detect.
            regions: Optional list of region names to process. None = all.
            condition: Optional condition filter.
            progress_callback: Optional callback(current, total, region_name).

        Returns:
            SegmentationResult with run statistics.

        Raises:
            ChannelNotFoundError: If the channel doesn't exist.
            ValueError: If no regions match the filter.
        """
        start = time.monotonic()
        warnings: list[str] = []

        # 1. Validate channel exists
        store.get_channel(channel)

        # 2. Create segmentation params
        params = SegmentationParams(
            channel=channel,
            model_name=model,
            diameter=float(diameter) if diameter is not None else None,
        )

        # 3. Instantiate CellposeAdapter if no segmenter provided
        segmenter = self._segmenter
        if segmenter is None:
            from percell3.segment.cellpose_adapter import CellposeAdapter

            segmenter = CellposeAdapter()

        # 4. Get regions to segment
        all_regions = store.get_regions(condition=condition)
        if regions is not None:
            region_set = set(regions)
            all_regions = [r for r in all_regions if r.name in region_set]

        if not all_regions:
            raise ValueError(
                "No regions match the filter. "
                f"condition={condition!r}, regions={regions!r}"
            )

        # 5. Create segmentation run in DB
        run_id = store.add_segmentation_run(
            channel, model, params.to_dict()
        )

        # 6. Process each region (one at a time for memory streaming)
        processor = LabelProcessor()
        total_cells = 0
        regions_processed = 0
        total = len(all_regions)

        for i, region_info in enumerate(all_regions):
            try:
                # Read image
                image = store.read_image_numpy(
                    region_info.name, region_info.condition, channel
                )

                # Run segmentation
                labels = segmenter.segment(image, params)

                # Write labels to zarr
                store.write_labels(
                    region_info.name, region_info.condition, labels, run_id
                )

                # Extract cell properties
                cells = processor.extract_cells(
                    labels,
                    region_info.id,
                    run_id,
                    region_info.pixel_size_um,
                )

                # Insert cells into DB
                if cells:
                    store.add_cells(cells)

                total_cells += len(cells)
                regions_processed += 1

                if len(cells) == 0:
                    warnings.append(
                        f"{region_info.name}: 0 cells detected"
                    )

            except Exception as exc:
                # Per-region error: log warning, continue with next region
                warnings.append(
                    f"{region_info.name}: segmentation failed — {exc}"
                )

            if progress_callback:
                progress_callback(i + 1, total, region_info.name)

        # 7. Update cell count in segmentation run
        store.update_segmentation_run_cell_count(run_id, total_cells)

        elapsed = time.monotonic() - start

        return SegmentationResult(
            run_id=run_id,
            cell_count=total_cells,
            regions_processed=regions_processed,
            warnings=warnings,
            elapsed_seconds=round(elapsed, 3),
        )
