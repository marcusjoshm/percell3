"""SegmentationEngine — pipeline orchestration for segmentation batches.

Ported from percell3.segment._engine with UUID-based IDs, cell identity
propagation, and MeasurementNeeded pattern.

Key differences from percell3:
    - All IDs are bytes UUIDs (not integers)
    - Creates cell_identity records for each ROI
    - Produces a single segmentation_set shared across all FOVs
    - Returns MeasurementNeeded items via assign_segmentation
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable

import numpy as np

from percell4.core.db_types import new_uuid, uuid_to_hex, uuid_to_str
from percell4.core.experiment_store import ExperimentStore
from percell4.core.models import MeasurementNeeded
from percell4.segment.label_processor import extract_rois

logger = logging.getLogger(__name__)


class SegmentationEngine:
    """Orchestrates segmentation across experiment FOVs.

    Creates a single segmentation_set shared across all FOVs in the
    batch, writes label images to Zarr, populates ROIs with cell
    identities, and triggers measurements via the MeasurementNeeded
    pattern.
    """

    def run(
        self,
        store: ExperimentStore,
        fov_ids: list[bytes],
        channel_name: str,
        roi_type_name: str,
        segmenter: Any,
        parameters: dict | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> tuple[bytes, list[MeasurementNeeded]]:
        """Run segmentation on a batch of FOVs.

        Args:
            store: An open ExperimentStore.
            fov_ids: List of FOV UUIDs to segment.
            channel_name: Channel name to segment on (e.g. "DAPI").
            roi_type_name: Name of the ROI type to produce (e.g. "cell").
            segmenter: Object with a ``segment(image, **kwargs) -> ndarray``
                method (CellposeSegmenter or MockSegmenter).
            parameters: Optional dict of segmentation parameters (stored in
                segmentation_set.parameters and pipeline_run.config_snapshot).
            on_progress: Optional callback(current, total) for progress.

        Returns:
            Tuple of (segmentation_set_id, list_of_MeasurementNeeded).

        Raises:
            ValueError: If channel or ROI type not found, or no FOVs given.
        """
        if not fov_ids:
            raise ValueError("fov_ids must not be empty")

        params = parameters or {}
        db = store.db

        # 1. Look up experiment
        exp = db.get_experiment()
        if exp is None:
            raise ValueError("No experiment found in database")
        exp_id = exp["id"]

        # 2. Look up channel by name
        channels = db.get_channels(exp_id)
        channel_row = None
        for ch in channels:
            if ch["name"] == channel_name:
                channel_row = ch
                break
        if channel_row is None:
            raise ValueError(
                f"Channel {channel_name!r} not found. "
                f"Available: {[ch['name'] for ch in channels]}"
            )

        # 3. Look up roi_type by name
        roi_types = db.get_roi_type_definitions(exp_id)
        roi_type_row = None
        for rt in roi_types:
            if rt["name"] == roi_type_name:
                roi_type_row = rt
                break
        if roi_type_row is None:
            raise ValueError(
                f"ROI type {roi_type_name!r} not found. "
                f"Available: {[rt['name'] for rt in roi_types]}"
            )
        roi_type_id = roi_type_row["id"]

        # 4. Create pipeline_run record
        run_id = new_uuid()
        config_snapshot = json.dumps(params) if params else None
        with store.db.transaction():
            db.insert_pipeline_run(
                run_id, "segmentation", config_snapshot=config_snapshot
            )

        # 5. Create segmentation_set record (shared across all FOVs)
        seg_set_id = new_uuid()
        model_name = params.get("model_name")
        with store.db.transaction():
            db.insert_segmentation_set(
                id=seg_set_id,
                experiment_id=exp_id,
                produces_roi_type_id=roi_type_id,
                seg_type=params.get("seg_type", "cellular"),
                source_channel=channel_name,
                model_name=model_name,
                parameters=json.dumps(params) if params else None,
                fov_count=0,
                total_roi_count=0,
            )

        # 6. Process each FOV
        total = len(fov_ids)
        total_roi_count = 0
        fov_count = 0
        all_measurement_needed: list[MeasurementNeeded] = []

        for idx, fov_id in enumerate(fov_ids):
            try:
                fov = db.get_fov(fov_id)
                if fov is None:
                    logger.warning(
                        "FOV %s not found, skipping", uuid_to_str(fov_id)
                    )
                    continue

                fov_hex = uuid_to_hex(fov_id)

                # Read image channel
                # Find channel index from display_order
                channel_index = channel_row["display_order"]
                image = store.layers.read_image_channel_numpy(
                    fov_hex, channel_index
                )

                # Run segmentation
                labels = segmenter.segment(image, **params)
                labels = np.asarray(labels, dtype=np.int32)

                # Write labels to LayerStore
                seg_set_hex = uuid_to_hex(seg_set_id)
                store.layers.write_labels(seg_set_hex, fov_hex, labels)

                # Extract ROIs from label image
                roi_dicts = extract_rois(labels)

                # Create cell identities and insert ROIs
                with store.db.transaction():
                    for roi_dict in roi_dicts:
                        # Create cell_identity (new for first segmentation)
                        ci_id = new_uuid()
                        db.insert_cell_identity(
                            ci_id, fov_id, roi_type_id
                        )

                        # Insert ROI
                        roi_id = new_uuid()
                        db.insert_roi(
                            id=roi_id,
                            fov_id=fov_id,
                            roi_type_id=roi_type_id,
                            cell_identity_id=ci_id,
                            parent_roi_id=None,
                            label_id=roi_dict["label_id"],
                            bbox_y=roi_dict["bbox_y"],
                            bbox_x=roi_dict["bbox_x"],
                            bbox_h=roi_dict["bbox_h"],
                            bbox_w=roi_dict["bbox_w"],
                            area_px=roi_dict["area_px"],
                        )

                # Assign segmentation to FOV
                with store.db.transaction():
                    needed = db.assign_segmentation(
                        [fov_id],
                        seg_set_id,
                        roi_type_id,
                        run_id,
                        assigned_by="segmentation_engine",
                    )
                    all_measurement_needed.extend(needed)

                fov_count += 1
                total_roi_count += len(roi_dicts)

                logger.info(
                    "Segmented FOV %s: %d ROIs",
                    uuid_to_str(fov_id), len(roi_dicts),
                )

            except Exception as exc:
                if isinstance(exc, (MemoryError, KeyboardInterrupt, SystemExit)):
                    raise
                logger.warning(
                    "Segmentation failed for FOV %s: %s",
                    uuid_to_str(fov_id), exc, exc_info=True,
                )

            if on_progress is not None:
                on_progress(idx + 1, total)

        # 7. Update segmentation_set counts
        with store.db.transaction():
            db.connection.execute(
                "UPDATE segmentation_sets "
                "SET fov_count = ?, total_roi_count = ? "
                "WHERE id = ?",
                (fov_count, total_roi_count, seg_set_id),
            )

        # 8. Complete pipeline_run
        with store.db.transaction():
            db.complete_pipeline_run(run_id, status="completed")

        return seg_set_id, all_measurement_needed
