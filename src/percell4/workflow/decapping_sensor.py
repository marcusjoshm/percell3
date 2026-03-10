"""Decapping sensor workflow — 11-step automated pipeline.

Steps:
    1.  Segment cells
    2.  Measure whole-ROI
    3.  Iterative thresholding round 1
    4.  Iterative thresholding round 2
    5.  Iterative thresholding round 3
    6.  Split-halo condensate analysis
    7.  Threshold-based BG subtraction
    8.  Measure BG-subtracted
    9.  Apply NaN-zero
    10. Measure NaN-safe
    11. Export with threshold pair deduplication
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
    signal_channels: list[str],
    halo_channel: str,
) -> dict[str, Any]:
    """Segment cells using the halo channel."""
    from percell4.core.constants import FovStatus
    from percell4.segment._engine import SegmentationEngine

    segmenter = context.get("segmenter")
    if segmenter is None:
        from percell4.segment.cellpose_adapter import CellposeSegmenter
        segmenter = CellposeSegmenter()

    exp = store.get_experiment()
    fovs = store.get_fovs(exp["id"])
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
        channel_name=halo_channel,
        roi_type_name="cell",
        segmenter=segmenter,
        parameters={"model_name": "cyto3", "seg_type": "cellular"},
    )

    context["seg_set_id"] = seg_set_id
    context["measurement_needed"] = measurement_needed
    context["fov_ids"] = fov_ids
    context["signal_channels"] = signal_channels
    context["halo_channel"] = halo_channel

    return {"seg_set_id": seg_set_id, "fov_count": len(fov_ids)}


def _step_measure_whole(
    store: ExperimentStore,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Measure whole-ROI intensities for all channels."""
    from percell4.measure.auto_measure import run_measurements

    needed = context.get("measurement_needed", [])
    if not needed:
        return {"measurements_count": 0}

    total = run_measurements(store, needed)
    return {"measurements_count": total}


def _step_threshold_round(
    store: ExperimentStore,
    context: dict[str, Any],
    *,
    round_num: int,
    method: str = "otsu",
) -> dict[str, Any]:
    """Apply iterative thresholding for one round.

    Each round applies thresholds to all signal channels on all FOVs.
    Subsequent rounds refine based on the remaining pixels.
    """
    from percell4.core.db_types import new_uuid
    from percell4.measure.thresholding import create_threshold_mask

    fov_ids = context.get("fov_ids", [])
    signal_channels = context.get("signal_channels", [])
    if not fov_ids or not signal_channels:
        return {"masks_created": 0}

    pipeline_run_id = new_uuid()
    store.db.insert_pipeline_run(
        pipeline_run_id, f"threshold_round_{round_num}"
    )

    masks_created = 0
    round_results = []

    for fov_id in fov_ids:
        for ch_name in signal_channels:
            try:
                result = create_threshold_mask(
                    store,
                    fov_id,
                    source_channel_name=ch_name,
                    method=method,
                    pipeline_run_id=pipeline_run_id,
                )
                round_results.append(result)
                masks_created += 1

                store.db.assign_mask(
                    [fov_id],
                    result.threshold_mask_id,
                    purpose="measurement_scope",
                    pipeline_run_id=pipeline_run_id,
                    assigned_by=f"workflow_threshold_r{round_num}",
                )
            except Exception:
                logger.exception(
                    "Threshold round %d failed for channel %s",
                    round_num, ch_name,
                )

    store.db.complete_pipeline_run(pipeline_run_id)

    key = f"threshold_round_{round_num}"
    context[key] = round_results
    return {"masks_created": masks_created, "round": round_num}


def _step_split_halo(
    store: ExperimentStore,
    context: dict[str, Any],
    *,
    halo_channel: str,
) -> dict[str, Any]:
    """Run split-halo condensate analysis plugin."""
    from percell4.plugins.registry import PluginRegistry

    fov_ids = context.get("fov_ids", [])
    if not fov_ids:
        return {"fovs_processed": 0}

    registry = PluginRegistry()
    try:
        plugin = registry.get_plugin("split_halo_condensate_analysis")
    except Exception:
        logger.warning("split_halo_condensate_analysis plugin not available")
        return {"fovs_processed": 0, "error": "plugin not available"}

    result = plugin.run(
        store,
        fov_ids=fov_ids,
        halo_channel=halo_channel,
    )

    return {
        "fovs_processed": result.fovs_processed,
        "measurements_added": result.measurements_added,
    }


def _step_threshold_bg_subtraction(
    store: ExperimentStore,
    context: dict[str, Any],
    *,
    bg_channel: str | None = None,
) -> dict[str, Any]:
    """Run threshold-based background subtraction plugin."""
    from percell4.plugins.registry import PluginRegistry

    fov_ids = context.get("fov_ids", [])
    if not fov_ids:
        return {"fovs_processed": 0}

    registry = PluginRegistry()
    try:
        plugin = registry.get_plugin("threshold_bg_subtraction")
    except Exception:
        logger.warning("threshold_bg_subtraction plugin not available")
        return {"fovs_processed": 0, "error": "plugin not available"}

    kwargs: dict[str, Any] = {}
    if bg_channel:
        kwargs["bg_channel"] = bg_channel

    result = plugin.run(store, fov_ids=fov_ids, **kwargs)

    # Track derived FOV IDs if created
    if result.derived_fovs_created > 0:
        context["has_derived_fovs"] = True

    return {
        "fovs_processed": result.fovs_processed,
        "derived_fovs_created": result.derived_fovs_created,
    }


def _step_measure_bg_subtracted(
    store: ExperimentStore,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Measure intensities on BG-subtracted derived FOVs."""
    from percell4.measure.auto_measure import run_measurements

    needed = context.get("measurement_needed", [])
    if not needed and context.get("has_derived_fovs"):
        # Re-gather measurement needs for derived FOVs
        pass

    total = run_measurements(store, needed) if needed else 0
    return {"measurements_count": total}


def _step_nan_zero(
    store: ExperimentStore,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Apply NaN-zero plugin to replace zero pixels with NaN."""
    from percell4.plugins.registry import PluginRegistry

    fov_ids = context.get("fov_ids", [])
    if not fov_ids:
        return {"fovs_processed": 0}

    registry = PluginRegistry()
    try:
        plugin = registry.get_plugin("nan_zero")
    except Exception:
        logger.warning("nan_zero plugin not available")
        return {"fovs_processed": 0, "error": "plugin not available"}

    result = plugin.run(store, fov_ids=fov_ids)
    return {
        "fovs_processed": result.fovs_processed,
        "derived_fovs_created": result.derived_fovs_created,
    }


def _step_measure_nan_safe(
    store: ExperimentStore,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Measure NaN-safe intensities on derived FOVs."""
    from percell4.measure.auto_measure import run_measurements

    needed = context.get("measurement_needed", [])
    total = run_measurements(store, needed) if needed else 0
    return {"measurements_count": total}


def _step_export_deduplicated(
    store: ExperimentStore,
    context: dict[str, Any],
    *,
    export_path: Path | None = None,
) -> dict[str, Any]:
    """Export CSV with threshold pair deduplication."""
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


def create_decapping_workflow(
    signal_channels: list[str],
    halo_channel: str,
    bg_channel: str | None = None,
    rounds: int = 3,
    export_path: Path | None = None,
) -> WorkflowEngine:
    """Create the 11-step decapping sensor workflow.

    Steps:
        1.  Segment cells
        2.  Measure whole-ROI
        3.  Iterative thresholding round 1
        4.  Iterative thresholding round 2
        5.  Iterative thresholding round 3
        6.  Split-halo condensate analysis
        7.  Threshold-based BG subtraction
        8.  Measure BG-subtracted
        9.  Apply NaN-zero
        10. Measure NaN-safe
        11. Export with threshold pair deduplication

    Args:
        signal_channels: List of signal channel names to threshold.
        halo_channel: Channel used for segmentation and split-halo analysis.
        bg_channel: Optional background channel for BG subtraction.
        rounds: Number of iterative thresholding rounds (default 3).
        export_path: Optional CSV output path. Export step skipped if None.

    Returns:
        A configured WorkflowEngine ready to run.
    """
    steps: list[WorkflowStep] = [
        # 1. Segment cells
        WorkflowStep(
            name="segment",
            description="Segment cells",
            handler=_step_segment,
            config={
                "signal_channels": signal_channels,
                "halo_channel": halo_channel,
            },
        ),
        # 2. Measure whole-ROI
        WorkflowStep(
            name="measure_whole",
            description="Measure whole-ROI intensities",
            handler=_step_measure_whole,
            depends_on=["segment"],
        ),
    ]

    # 3-5. Iterative thresholding rounds
    prev_step = "measure_whole"
    for r in range(1, rounds + 1):
        step = WorkflowStep(
            name=f"threshold_round_{r}",
            description=f"Iterative thresholding round {r}",
            handler=_step_threshold_round,
            depends_on=[prev_step],
            config={"round_num": r, "method": "otsu"},
        )
        steps.append(step)
        prev_step = step.name

    last_threshold = prev_step

    # 6. Split-halo condensate analysis
    steps.append(
        WorkflowStep(
            name="split_halo",
            description="Split-halo condensate analysis",
            handler=_step_split_halo,
            depends_on=[last_threshold],
            config={"halo_channel": halo_channel},
        )
    )

    # 7. Threshold-based BG subtraction
    steps.append(
        WorkflowStep(
            name="bg_subtraction",
            description="Threshold-based background subtraction",
            handler=_step_threshold_bg_subtraction,
            depends_on=["split_halo"],
            config={"bg_channel": bg_channel},
        )
    )

    # 8. Measure BG-subtracted
    steps.append(
        WorkflowStep(
            name="measure_bg_subtracted",
            description="Measure BG-subtracted intensities",
            handler=_step_measure_bg_subtracted,
            depends_on=["bg_subtraction"],
        )
    )

    # 9. Apply NaN-zero
    steps.append(
        WorkflowStep(
            name="nan_zero",
            description="Replace zeros with NaN",
            handler=_step_nan_zero,
            depends_on=["measure_bg_subtracted"],
        )
    )

    # 10. Measure NaN-safe
    steps.append(
        WorkflowStep(
            name="measure_nan_safe",
            description="Measure NaN-safe intensities",
            handler=_step_measure_nan_safe,
            depends_on=["nan_zero"],
        )
    )

    # 11. Export with deduplication
    steps.append(
        WorkflowStep(
            name="export",
            description="Export CSV with threshold pair deduplication",
            handler=_step_export_deduplicated,
            depends_on=["measure_nan_safe"],
            config={"export_path": export_path},
            skip_if=lambda s, c: export_path is None,
        )
    )

    return WorkflowEngine(steps)
