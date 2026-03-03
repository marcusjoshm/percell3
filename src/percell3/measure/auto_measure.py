"""Auto-measurement pipeline — triggers measurements as a side effect of layer operations.

This module provides event-driven functions that automatically compute measurements
when segmentation or thresholding layers are created/modified. Measurement failures
never roll back the layer creation.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

from percell3.core.models import CellRecord
from percell3.measure.measurer import Measurer
from percell3.measure.particle_analyzer import ParticleAnalyzer

if TYPE_CHECKING:
    from percell3.core import ExperimentStore
    from percell3.core.models import FovConfigEntry

logger = logging.getLogger(__name__)


def on_segmentation_created(
    store: ExperimentStore,
    segmentation_id: int,
    fov_ids: list[int],
) -> int:
    """Auto-measure after a segmentation is created.

    For cellular segmentations: extract cells from labels and measure all
    channels with whole_cell scope for each FOV.

    For whole_field segmentations: create a single cell record (the entire FOV)
    and measure all channels.

    Args:
        store: Target ExperimentStore.
        segmentation_id: The newly created segmentation.
        fov_ids: FOVs to measure (from fov_config).

    Returns:
        Total number of measurements written.
    """
    seg = store.get_segmentation(segmentation_id)
    channels = store.get_channels()
    if not channels:
        logger.warning("No channels configured — skipping auto-measurement")
        return 0

    channel_names = [ch.name for ch in channels]
    total = 0
    measurer = Measurer()

    for fov_id in fov_ids:
        try:
            # Extract cells from labels if none exist yet
            cells_df = store.get_cells(fov_id=fov_id)
            seg_cells = cells_df[cells_df["segmentation_id"] == segmentation_id] if not cells_df.empty else cells_df
            if seg_cells.empty:
                n_cells = _extract_cells_from_labels(store, fov_id, segmentation_id)
                if n_cells == 0:
                    logger.warning(
                        "No cells extracted from segmentation %d for FOV %d",
                        segmentation_id, fov_id,
                    )
                    continue

            count = measurer.measure_fov(
                store, fov_id, channel_names, segmentation_id,
            )
            if count == 0:
                logger.warning(
                    "0 measurements for segmentation %d, FOV %d",
                    segmentation_id, fov_id,
                )
            total += count
        except Exception:
            logger.exception(
                "Auto-measurement failed for segmentation %d, FOV %d",
                segmentation_id, fov_id,
            )

    return total


def on_threshold_created(
    store: ExperimentStore,
    threshold_id: int,
    fov_id: int,
    segmentation_id: int,
) -> int:
    """Auto-measure after a threshold is created.

    Extracts particles (connected components), assigns to cells, and
    measures all channels for mask_inside/mask_outside scopes.

    Args:
        store: Target ExperimentStore.
        threshold_id: The newly created threshold.
        fov_id: FOV to analyze.
        segmentation_id: Active segmentation for this FOV.

    Returns:
        Total number of measurements written.
    """
    channels = store.get_channels()
    if not channels:
        logger.warning("No channels configured — skipping auto-measurement")
        return 0

    channel_names = [ch.name for ch in channels]
    total = 0

    try:
        # Clean up stale particles so re-runs are idempotent
        store.delete_particles_for_fov_threshold(fov_id, threshold_id)

        # Particle analysis
        analyzer = ParticleAnalyzer()
        result = analyzer.analyze_fov(
            store, fov_id, threshold_id, segmentation_id,
        )

        if result.particles:
            store.add_particles(result.particles)
            store.write_particle_labels(result.particle_label_image, threshold_id)

        if result.summary_measurements:
            store.add_measurements(result.summary_measurements)
            total += len(result.summary_measurements)

        # Masked measurements (mask_inside/mask_outside)
        measurer = Measurer()
        count = measurer.measure_fov_masked(
            store, fov_id, channel_names,
            segmentation_id=segmentation_id,
            threshold_id=threshold_id,
            scopes=["mask_inside", "mask_outside"],
        )
        total += count

        if total == 0:
            logger.warning(
                "0 measurements for threshold %d, FOV %d",
                threshold_id, fov_id,
            )
    except Exception:
        logger.exception(
            "Auto-measurement failed for threshold %d, FOV %d",
            threshold_id, fov_id,
        )

    return total


def on_labels_edited(
    store: ExperimentStore,
    segmentation_id: int,
    old_labels: np.ndarray,
    new_labels: np.ndarray,
) -> int:
    """Update measurements after label edits.

    Detects whether labels changed, then deletes old cells/measurements
    for affected FOVs and re-extracts + re-measures from the new labels.
    Propagates to ALL FOVs referencing this segmentation.

    Args:
        store: Target ExperimentStore.
        segmentation_id: The edited segmentation.
        old_labels: Label image before edit.
        new_labels: Label image after edit.

    Returns:
        Total number of new measurements written.
    """
    # Quick check: any change at all?
    if np.array_equal(old_labels, new_labels):
        return 0

    # Find all FOVs referencing this segmentation
    config_entries = store.get_config_matrix()
    fov_ids = list({e.fov_id for e in config_entries if e.segmentation_id == segmentation_id})

    if not fov_ids:
        return 0

    total = 0
    for fov_id in fov_ids:
        try:
            # Delete all existing cells (cascade-deletes measurements) for this FOV
            store.delete_cells_for_fov(fov_id)

            # Re-extract cells and re-measure
            count = on_segmentation_created(store, segmentation_id, [fov_id])
            total += count
        except Exception:
            logger.exception(
                "Auto-measurement after label edit failed for segmentation %d, FOV %d",
                segmentation_id, fov_id,
            )

    return total


def on_config_changed(
    store: ExperimentStore,
    fov_id: int,
) -> int:
    """Fill measurement gaps after a config change.

    Detects unmeasured (seg, thresh) combinations and auto-computes
    missing measurements. Does NOT delete old measurements.

    Args:
        store: Target ExperimentStore.
        fov_id: The FOV whose config changed.

    Returns:
        Number of new measurements written.
    """
    config = store.get_fov_config(fov_id)
    if not config:
        return 0

    channels = store.get_channels()
    if not channels:
        return 0

    channel_names = [ch.name for ch in channels]
    total = 0

    for entry in config:
        try:
            # Check if whole_cell measurements exist for this segmentation
            if not _has_measurements(store, fov_id, entry.segmentation_id):
                count = on_segmentation_created(
                    store, entry.segmentation_id, [fov_id],
                )
                total += count

            # Check if masked measurements exist for this threshold
            if entry.threshold_id is not None:
                if not _has_masked_measurements(
                    store, fov_id, entry.segmentation_id, entry.threshold_id,
                ):
                    count = on_threshold_created(
                        store, entry.threshold_id, fov_id, entry.segmentation_id,
                    )
                    total += count
        except Exception:
            logger.exception(
                "Auto-measurement gap-fill failed for FOV %d, "
                "seg %d, thresh %s",
                fov_id, entry.segmentation_id, entry.threshold_id,
            )

    return total


# --- Helpers ---


def _extract_cells_from_labels(
    store: ExperimentStore,
    fov_id: int,
    segmentation_id: int,
) -> int:
    """Extract cell records from a label image.

    Uses skimage.measure.regionprops to compute centroids, bounding boxes,
    and areas from the label image.

    Args:
        store: Target ExperimentStore.
        fov_id: FOV database ID.
        segmentation_id: Segmentation to extract from.

    Returns:
        Number of cells created.
    """
    from skimage.measure import regionprops

    labels = store.read_labels(segmentation_id)
    props = regionprops(np.asarray(labels))

    cells: list[CellRecord] = []
    for prop in props:
        cy, cx = prop.centroid
        min_row, min_col, max_row, max_col = prop.bbox

        cells.append(CellRecord(
            fov_id=fov_id,
            segmentation_id=segmentation_id,
            label_value=prop.label,
            centroid_x=float(cx),
            centroid_y=float(cy),
            bbox_x=min_col,
            bbox_y=min_row,
            bbox_w=max_col - min_col,
            bbox_h=max_row - min_row,
            area_pixels=float(prop.area),
        ))

    if cells:
        store.add_cells(cells)
        store.update_segmentation_cell_count(segmentation_id, len(cells))

    return len(cells)


def _has_measurements(
    store: ExperimentStore,
    fov_id: int,
    segmentation_id: int,
) -> bool:
    """Check if whole_cell measurements exist for this seg+fov."""
    cells_df = store.get_cells(fov_id=fov_id)
    if cells_df.empty:
        return False

    seg_cells = cells_df[cells_df["segmentation_id"] == segmentation_id]
    if seg_cells.empty:
        return False

    # Check if measurements exist for any cell in this segmentation
    cell_id = int(seg_cells.iloc[0]["id"])
    measurements = store.get_measurements(cell_ids=[cell_id])
    return len(measurements) > 0


def _has_masked_measurements(
    store: ExperimentStore,
    fov_id: int,
    segmentation_id: int,
    threshold_id: int,
) -> bool:
    """Check if mask_inside measurements exist for this seg+thresh+fov."""
    cells_df = store.get_cells(fov_id=fov_id)
    if cells_df.empty:
        return False

    seg_cells = cells_df[cells_df["segmentation_id"] == segmentation_id]
    if seg_cells.empty:
        return False

    cell_id = int(seg_cells.iloc[0]["id"])
    measurements = store.get_measurements(cell_ids=[cell_id])
    if measurements.empty:
        return False

    # Check for mask_inside scope with this threshold
    return any(
        (measurements["scope"] == "mask_inside") &
        (measurements["threshold_id"] == threshold_id)
    )
