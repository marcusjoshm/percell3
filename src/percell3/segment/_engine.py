"""SegmentationEngine — pipeline orchestration for segmentation batches."""

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
from percell3.segment.label_processor import (
    LabelProcessor,
    extract_cells,
    filter_edge_cells,
    filter_small_cells,
)

logger = logging.getLogger(__name__)


class SegmentationEngine:
    """Orchestrates a full segmentation batch across experiment FOVs.

    Creates one global segmentation entity per FOV, writes label images
    to ``labels.zarr``, populates the ``cells`` table, and triggers
    auto-measurement via the auto_measure pipeline.

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

        Creates one global segmentation entity per FOV, writes labels,
        extracts cells, and triggers auto-measurement.

        Args:
            store: Target ExperimentStore.
            channel: Channel name to segment.
            model: Cellpose model name (e.g., "cpsam", "cyto3", "nuclei").
            diameter: Expected cell diameter in pixels. None = auto-detect.
            fovs: Optional list of FOV display names to process. None = all.
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
                "edge_margin", "min_area",
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
            all_fovs = [f for f in all_fovs if f.display_name in fov_set]

        if not all_fovs:
            raise ValueError(
                "No FOVs match the filter. "
                f"condition={condition!r}, fovs={fovs!r}"
            )

        # 5. Process each FOV (one global segmentation per FOV)
        total_cells = 0
        fovs_processed = 0
        total = len(all_fovs)
        last_seg_id: int | None = None

        for i, fov_info in enumerate(all_fovs):
            try:
                # Read image
                image = store.read_image_numpy(fov_info.id, channel)

                # Run segmentation
                labels = segmenter.segment(image, params)

                # Post-segmentation label cleanup
                if params.edge_margin is not None:
                    labels, n_removed = filter_edge_cells(
                        labels, params.edge_margin,
                    )
                    if n_removed:
                        logger.info(
                            "Removed %d edge cell(s) from FOV %s",
                            n_removed, fov_info.display_name,
                        )
                if params.min_area is not None:
                    labels, n_small = filter_small_cells(
                        labels, params.min_area,
                    )
                    if n_small:
                        logger.info(
                            "Removed %d small cell(s) (<%d px) from FOV %s",
                            n_small, params.min_area, fov_info.display_name,
                        )

                h, w = labels.shape

                # Create one global segmentation entity per FOV
                name = store._generate_segmentation_name(
                    params.model_name, channel,
                )
                seg_id = store.add_segmentation(
                    name=name, seg_type="cellular",
                    width=w, height=h,
                    source_fov_id=fov_info.id, source_channel=channel,
                    model_name=params.model_name,
                    parameters=params.to_dict(),
                )
                last_seg_id = seg_id

                # Write labels to zarr
                store.write_labels(labels, seg_id)

                # Extract cell properties
                cells = extract_cells(
                    labels,
                    fov_info.id,
                    seg_id,
                    fov_info.pixel_size_um,
                )

                # Insert cells into DB
                if cells:
                    store.add_cells(cells)

                # Update cell count
                store.update_segmentation_cell_count(seg_id, len(cells))

                # Trigger auto-measurement
                try:
                    from percell3.measure.auto_measure import on_segmentation_created
                    on_segmentation_created(store, seg_id, [fov_info.id])
                except Exception as exc:
                    logger.warning(
                        "Auto-measurement failed for FOV %s: %s",
                        fov_info.display_name, exc,
                    )

                total_cells += len(cells)
                fovs_processed += 1

                fov_stats.append({
                    "fov": fov_info.display_name,
                    "cell_count": len(cells),
                    "segmentation_id": seg_id,
                    "status": "ok",
                })

                if len(cells) == 0:
                    warnings.append(
                        f"{fov_info.display_name}: 0 cells detected"
                    )

            except Exception as exc:
                if isinstance(exc, (MemoryError, KeyboardInterrupt, SystemExit)):
                    raise
                logger.warning(
                    "Segmentation failed for FOV %s: %s",
                    fov_info.display_name, exc, exc_info=True,
                )
                warnings.append(
                    f"{fov_info.display_name}: segmentation failed — {exc}"
                )
                fov_stats.append({
                    "fov": fov_info.display_name,
                    "cell_count": 0,
                    "status": "failed",
                    "error": str(exc),
                })

            if progress_callback:
                progress_callback(i + 1, total, fov_info.display_name)

        elapsed = time.monotonic() - start

        return SegmentationResult(
            run_id=last_seg_id or 0,
            cell_count=total_cells,
            fovs_processed=fovs_processed,
            warnings=warnings,
            elapsed_seconds=round(elapsed, 3),
            fov_stats=fov_stats,
        )
