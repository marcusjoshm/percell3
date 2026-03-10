"""Particle analysis workflow — standard pipeline.

Steps:
    1. Segment cells
    2. Measure whole-ROI for all channels
    3. Apply grouped intensity thresholds
    4. Measure masked scopes
    5. Export CSV
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from percell4.workflow.engine import WorkflowEngine, WorkflowStep

if TYPE_CHECKING:
    from percell4.core.experiment_store import ExperimentStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Step handlers
# ---------------------------------------------------------------------------


def _step_segment(
    store: ExperimentStore,
    context: dict[str, Any],
    *,
    channel_name: str,
    roi_type_name: str = "cell",
    model_name: str = "cyto3",
    diameter: float = 30.0,
) -> dict[str, Any]:
    """Run segmentation on all imported FOVs.

    Writes seg_set_id and measurement_needed into context for downstream use.
    """
    from percell4.core.constants import FovStatus
    from percell4.segment._engine import SegmentationEngine
    from percell4.segment.cellpose_adapter import CellposeSegmenter

    # Use a segmenter from context if provided (for testing), otherwise real
    segmenter = context.get("segmenter")
    if segmenter is None:
        segmenter = CellposeSegmenter()

    # Get all imported FOVs
    exp = store.db.get_experiment()
    fovs = store.db.get_fovs(exp["id"])
    fov_ids = [
        f["id"]
        for f in fovs
        if f["status"] in (FovStatus.imported, "imported")
    ]

    if not fov_ids:
        logger.warning("No imported FOVs to segment")
        return {"fov_count": 0}

    engine = SegmentationEngine()
    seg_set_id, measurement_needed = engine.run(
        store=store,
        fov_ids=fov_ids,
        channel_name=channel_name,
        roi_type_name=roi_type_name,
        segmenter=segmenter,
        parameters={
            "model_name": model_name,
            "diameter": diameter,
            "seg_type": "cellular",
        },
    )

    context["seg_set_id"] = seg_set_id
    context["measurement_needed"] = measurement_needed
    context["fov_ids"] = fov_ids

    return {
        "seg_set_id": seg_set_id,
        "fov_count": len(fov_ids),
        "measurement_needed": len(measurement_needed),
    }


def _step_measure_whole(
    store: ExperimentStore,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Measure whole-ROI intensities for all channels.

    Reads measurement_needed from context (set by segment step).
    """
    from percell4.measure.auto_measure import run_measurements

    needed = context.get("measurement_needed", [])
    if not needed:
        logger.warning("No measurement_needed items — skipping")
        return {"measurements_count": 0}

    total = run_measurements(store, needed)
    return {"measurements_count": total}


def _step_threshold(
    store: ExperimentStore,
    context: dict[str, Any],
    *,
    method: str = "otsu",
) -> dict[str, Any]:
    """Apply intensity thresholds to all FOVs on all channels.

    Creates threshold masks and assigns them for measurement scoping.
    """
    from percell4.core.db_types import new_uuid
    from percell4.measure.thresholding import create_threshold_mask

    fov_ids = context.get("fov_ids", [])
    if not fov_ids:
        return {"masks_created": 0}

    exp = store.db.get_experiment()
    channels = store.db.get_channels(exp["id"])

    masks_created = 0
    threshold_results = []
    pipeline_run_id = new_uuid()
    store.db.insert_pipeline_run(pipeline_run_id, "threshold")

    for fov_id in fov_ids:
        for ch in channels:
            try:
                result = create_threshold_mask(
                    store,
                    fov_id,
                    source_channel_name=ch["name"],
                    method=method,
                    pipeline_run_id=pipeline_run_id,
                )
                threshold_results.append(result)
                masks_created += 1

                # Assign mask for measurement scoping
                store.db.assign_mask(
                    [fov_id],
                    result.threshold_mask_id,
                    purpose="measurement_scope",
                    pipeline_run_id=pipeline_run_id,
                    assigned_by="workflow_threshold",
                )
            except Exception:
                logger.exception(
                    "Threshold failed for FOV on channel %s", ch["name"]
                )

    store.db.complete_pipeline_run(pipeline_run_id)
    context["threshold_results"] = threshold_results
    return {"masks_created": masks_created}


def _step_measure_masked(
    store: ExperimentStore,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Measure masked scopes (mask_inside, mask_outside) for all FOVs.

    Reads fov_ids and seg_set_id from context.
    """
    from percell4.core.constants import SCOPE_MASK_INSIDE, SCOPE_MASK_OUTSIDE
    from percell4.core.db_types import new_uuid
    from percell4.measure.measurer import Measurer

    fov_ids = context.get("fov_ids", [])
    seg_set_id = context.get("seg_set_id")
    if not fov_ids or seg_set_id is None:
        return {"measurements_count": 0}

    measurer = Measurer()
    exp = store.db.get_experiment()
    channels = store.db.get_channels(exp["id"])

    # Find roi_type from segmentation_set
    seg_set = store.db.get_segmentation_set(seg_set_id)
    roi_type_id = seg_set["produces_roi_type_id"]

    pipeline_run_id = new_uuid()
    store.db.insert_pipeline_run(pipeline_run_id, "measure_masked")

    total = 0
    for fov_id in fov_ids:
        # Get active mask assignments for this FOV
        assignments = store.db.get_active_assignments(fov_id)
        mask_assignments = assignments.get("mask", [])

        for ma in mask_assignments:
            if ma["purpose"] != "measurement_scope":
                continue
            for ch in channels:
                try:
                    n = measurer.measure_fov_masked(
                        store,
                        fov_id=fov_id,
                        channel_id=ch["id"],
                        seg_set_id=seg_set_id,
                        roi_type_id=roi_type_id,
                        mask_id=ma["threshold_mask_id"],
                        scopes=[SCOPE_MASK_INSIDE, SCOPE_MASK_OUTSIDE],
                        pipeline_run_id=pipeline_run_id,
                    )
                    total += n
                except Exception:
                    logger.exception(
                        "Masked measurement failed for FOV on channel %s",
                        ch["name"],
                    )

    store.db.complete_pipeline_run(pipeline_run_id)
    return {"measurements_count": total}


def _step_export(
    store: ExperimentStore,
    context: dict[str, Any],
    *,
    export_path: Path | None = None,
) -> dict[str, Any]:
    """Export measurements to CSV."""
    if export_path is None:
        return {"rows_exported": 0}

    fov_ids = context.get("fov_ids", [])
    if not fov_ids:
        return {"rows_exported": 0}

    rows = store.export_measurements_csv(fov_ids, Path(export_path))
    return {"rows_exported": rows, "path": str(export_path)}


# ---------------------------------------------------------------------------
# Workflow factory
# ---------------------------------------------------------------------------


def create_particle_analysis_workflow(
    channel_name: str,
    roi_type_name: str = "cell",
    model_name: str = "cyto3",
    diameter: float = 30.0,
    threshold_method: str = "otsu",
    export_path: Path | None = None,
) -> WorkflowEngine:
    """Create a standard particle analysis workflow.

    Steps:
        1. Segment cells
        2. Measure whole-cell for all channels
        3. Apply grouped intensity thresholds
        4. Measure masked scopes
        5. Export CSV

    Args:
        channel_name: Channel to segment on (e.g., "DAPI").
        roi_type_name: ROI type to produce (e.g., "cell").
        model_name: Cellpose model name.
        diameter: Expected cell diameter in pixels.
        threshold_method: Thresholding method (otsu, triangle, li, manual).
        export_path: Optional CSV output path. Export step skipped if None.

    Returns:
        A configured WorkflowEngine ready to run.
    """
    steps = [
        WorkflowStep(
            name="segment",
            description="Segment cells",
            handler=_step_segment,
            config={
                "channel_name": channel_name,
                "roi_type_name": roi_type_name,
                "model_name": model_name,
                "diameter": diameter,
            },
        ),
        WorkflowStep(
            name="measure_whole",
            description="Measure whole-cell intensities",
            handler=_step_measure_whole,
            depends_on=["segment"],
        ),
        WorkflowStep(
            name="threshold",
            description="Apply intensity thresholds",
            handler=_step_threshold,
            depends_on=["measure_whole"],
            config={"method": threshold_method},
        ),
        WorkflowStep(
            name="measure_masked",
            description="Measure masked scopes",
            handler=_step_measure_masked,
            depends_on=["threshold"],
        ),
        WorkflowStep(
            name="export",
            description="Export CSV",
            handler=_step_export,
            depends_on=["measure_masked"],
            config={"export_path": export_path},
            skip_if=lambda s, c: export_path is None,
        ),
    ]
    return WorkflowEngine(steps)
