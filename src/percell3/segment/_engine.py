"""SegmentationEngine — pipeline orchestration for segmentation runs."""

from __future__ import annotations

import logging
import time
from typing import Callable

import numpy as np

from percell3.core import ExperimentStore
from percell3.core.exceptions import ChannelNotFoundError
from percell3.segment.base_segmenter import (
    BaseSegmenter,
    SegmentationParams,
    SegmentationResult,
)
from percell3.segment.label_processor import LabelProcessor

logger = logging.getLogger(__name__)


class SegmentationEngine:
    """Orchestrates a full segmentation run across experiment FOVs.

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
        model: str = "cpsam",
        diameter: int | float | None = None,
        fovs: list[str] | None = None,
        condition: str | None = None,
        bio_rep: str | None = None,
        progress_callback: Callable[[int, int, str], None] | None = None,
        params: SegmentationParams | None = None,
        **kwargs: object,
    ) -> SegmentationResult:
        """Run segmentation on experiment FOVs.

        Args:
            store: Target ExperimentStore.
            channel: Channel name to segment.
            model: Cellpose model name (e.g., "cpsam", "cyto3", "nuclei").
            diameter: Expected cell diameter in pixels. None = auto-detect.
            fovs: Optional list of FOV names to process. None = all.
            condition: Optional condition filter.
            progress_callback: Optional callback(current, total, fov_name).
            params: Optional pre-built SegmentationParams. If provided,
                channel/model/diameter/kwargs are ignored.
            **kwargs: Additional SegmentationParams fields (flow_threshold,
                cellprob_threshold, gpu, min_size, normalize, channels_cellpose).

        Returns:
            SegmentationResult with run statistics.

        Raises:
            ChannelNotFoundError: If the channel doesn't exist.
            ValueError: If no FOVs match the filter.
        """
        start = time.monotonic()
        warnings: list[str] = []
        fov_stats: list[dict[str, object]] = []

        # 1. Validate channel exists
        store.get_channel(channel)

        # 2. Create segmentation params
        if params is None:
            param_kwargs: dict[str, object] = {"channel": channel, "model_name": model}
            if diameter is not None:
                param_kwargs["diameter"] = float(diameter)
            for key in (
                "flow_threshold", "cellprob_threshold", "gpu",
                "min_size", "normalize", "channels_cellpose",
            ):
                if key in kwargs:
                    param_kwargs[key] = kwargs[key]
            params = SegmentationParams(**param_kwargs)  # type: ignore[arg-type]

        # 3. Instantiate CellposeAdapter if no segmenter provided
        segmenter = self._segmenter
        if segmenter is None:
            from percell3.segment.cellpose_adapter import CellposeAdapter

            segmenter = CellposeAdapter()

        # 4. Get FOVs to segment
        all_fovs = store.get_fovs(condition=condition, bio_rep=bio_rep)
        if fovs is not None:
            fov_set = set(fovs)
            all_fovs = [f for f in all_fovs if f.name in fov_set]

        if not all_fovs:
            raise ValueError(
                "No FOVs match the filter. "
                f"condition={condition!r}, fovs={fovs!r}"
            )

        # 5. Create segmentation run in DB
        run_id = store.add_segmentation_run(
            channel, params.model_name, params.to_dict()
        )

        # 6. Process each FOV (one at a time for memory streaming)
        processor = LabelProcessor()
        total_cells = 0
        fovs_processed = 0
        total = len(all_fovs)

        for i, fov_info in enumerate(all_fovs):
            try:
                # Read image
                image = store.read_image_numpy(
                    fov_info.name, fov_info.condition, channel,
                    bio_rep=fov_info.bio_rep,
                )

                # Run segmentation
                labels = segmenter.segment(image, params)

                # Write labels to zarr
                store.write_labels(
                    fov_info.name, fov_info.condition, labels, run_id,
                    bio_rep=fov_info.bio_rep,
                )

                # Extract cell properties
                cells = processor.extract_cells(
                    labels,
                    fov_info.id,
                    run_id,
                    fov_info.pixel_size_um,
                )

                # Delete existing cells for this FOV (re-segmentation)
                deleted = store.delete_cells_for_fov(
                    fov_info.name, fov_info.condition,
                )
                if deleted > 0:
                    logger.info(
                        "Replaced %d existing cells for FOV %s",
                        deleted, fov_info.name,
                    )

                # Insert cells into DB
                if cells:
                    store.add_cells(cells)

                total_cells += len(cells)
                fovs_processed += 1

                fov_stats.append({
                    "fov": fov_info.name,
                    "cell_count": len(cells),
                    "status": "ok",
                })

                if len(cells) == 0:
                    warnings.append(
                        f"{fov_info.name}: 0 cells detected"
                    )

            except Exception as exc:
                if isinstance(exc, (MemoryError, KeyboardInterrupt, SystemExit)):
                    raise
                logger.warning(
                    "Segmentation failed for FOV %s: %s",
                    fov_info.name, exc, exc_info=True,
                )
                warnings.append(
                    f"{fov_info.name}: segmentation failed — {exc}"
                )
                fov_stats.append({
                    "fov": fov_info.name,
                    "cell_count": 0,
                    "status": "failed",
                    "error": str(exc),
                })

            if progress_callback:
                progress_callback(i + 1, total, fov_info.name)

        # 7. Update cell count in segmentation run
        store.update_segmentation_run_cell_count(run_id, total_cells)

        elapsed = time.monotonic() - start

        return SegmentationResult(
            run_id=run_id,
            cell_count=total_cells,
            fovs_processed=fovs_processed,
            warnings=warnings,
            elapsed_seconds=round(elapsed, 3),
            fov_stats=fov_stats,
        )
