"""Import pre-existing label images into a PerCell 4 experiment.

Ported from percell3.segment.roi_import with UUID-based IDs and
cell identity propagation.
"""

from __future__ import annotations

import json
import logging

import numpy as np

from percell4.core.db_types import new_uuid, uuid_to_hex, uuid_to_str
from percell4.core.experiment_store import ExperimentStore
from percell4.segment.label_processor import extract_rois

logger = logging.getLogger(__name__)


def import_label_image(
    store: ExperimentStore,
    fov_id: bytes,
    label_image: np.ndarray,
    roi_type_name: str,
    pipeline_run_id: bytes,
) -> int:
    """Import a pre-computed label image into an experiment.

    Creates a segmentation_set, extracts ROIs, creates cell_identity
    records and ROI records, and assigns the segmentation to the FOV.

    Args:
        store: An open ExperimentStore.
        fov_id: FOV UUID to import labels for.
        label_image: 2D integer array where pixel value = ROI ID,
            0 = background.
        roi_type_name: Name of the ROI type (e.g. "cell").
        pipeline_run_id: Pipeline run UUID for provenance tracking.

    Returns:
        Count of ROIs imported.

    Raises:
        ValueError: If the label image is not 2D or not integer dtype,
            or if the ROI type is not found.
    """
    if not np.issubdtype(label_image.dtype, np.integer):
        raise ValueError(
            f"Labels must have integer dtype, got {label_image.dtype}. "
            "Cast to int32 before importing."
        )
    if label_image.ndim != 2:
        raise ValueError(
            f"Labels must be 2D, got {label_image.ndim}D with shape "
            f"{label_image.shape}"
        )

    db = store.db
    labels_int32 = np.asarray(label_image, dtype=np.int32)

    # Look up experiment
    exp = db.get_experiment()
    if exp is None:
        raise ValueError("No experiment found in database")
    exp_id = exp["id"]

    # Look up roi_type by name
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

    # Create segmentation_set for this import
    seg_set_id = new_uuid()
    with store.db.transaction():
        db.insert_segmentation_set(
            id=seg_set_id,
            experiment_id=exp_id,
            produces_roi_type_id=roi_type_id,
            seg_type="imported",
            source_channel="manual",
            model_name="manual_import",
            parameters=json.dumps({"source": "label_image_import"}),
            fov_count=1,
            total_roi_count=0,
        )

    # Write labels to LayerStore
    seg_set_hex = uuid_to_hex(seg_set_id)
    fov_hex = uuid_to_hex(fov_id)
    store.layers.write_labels(seg_set_hex, fov_hex, labels_int32)

    # Extract ROIs
    roi_dicts = extract_rois(labels_int32)

    # Create cell identities and ROIs
    with store.db.transaction():
        for roi_dict in roi_dicts:
            ci_id = new_uuid()
            db.insert_cell_identity(ci_id, fov_id, roi_type_id)

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

    # Update segmentation_set total_roi_count
    with store.db.transaction():
        db.connection.execute(
            "UPDATE segmentation_sets SET total_roi_count = ? WHERE id = ?",
            (len(roi_dicts), seg_set_id),
        )

    # Assign segmentation to FOV
    with store.db.transaction():
        db.assign_segmentation(
            [fov_id],
            seg_set_id,
            roi_type_id,
            pipeline_run_id,
            assigned_by="label_image_import",
        )

    logger.info(
        "Imported %d ROIs for FOV %s", len(roi_dicts), uuid_to_str(fov_id)
    )
    return len(roi_dicts)
