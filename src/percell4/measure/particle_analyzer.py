"""ParticleAnalyzer — connected component analysis within threshold masks.

Ported from percell3 with UUID IDs and unified ROI terminology.
Particles are sub-cellular ROIs linked to their parent cell ROI
via parent_roi_id.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from percell4.core.db_types import new_uuid, uuid_to_hex

if TYPE_CHECKING:
    from percell4.core.experiment_store import ExperimentStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParticleAnalysisResult:
    """Result of particle analysis for a FOV.

    Attributes:
        particles_created: Number of particle ROIs created.
        particle_label_image: Full FOV int32 label image with unique particle IDs.
        parent_rois_analyzed: Number of parent ROIs processed.
    """

    particles_created: int
    particle_label_image: np.ndarray
    parent_rois_analyzed: int


def analyze_particles(
    store: ExperimentStore,
    fov_id: bytes,
    mask_id: bytes,
    roi_type_name: str,
    pipeline_run_id: bytes,
    min_particle_area: int = 1,
) -> ParticleAnalysisResult:
    """Detect connected components within a threshold mask and create sub-ROIs.

    For each parent ROI (cell), intersects the threshold mask with the cell's
    label region, finds connected components, and creates child ROI records
    of the specified sub-cellular type.

    Args:
        store: Target ExperimentStore.
        fov_id: FOV database ID.
        mask_id: Threshold mask ID to analyze.
        roi_type_name: Name of the particle ROI type (e.g., "particle").
        pipeline_run_id: Pipeline run for provenance.
        min_particle_area: Minimum area in pixels to keep a particle.

    Returns:
        ParticleAnalysisResult with creation counts and label image.
    """
    from scipy.ndimage import label as scipy_label
    from skimage.measure import regionprops

    # Resolve the particle ROI type
    fov_row = store.db.get_fov(fov_id)
    experiment_id = fov_row["experiment_id"]
    roi_types = store.db.get_roi_type_definitions(experiment_id)
    particle_type_id = None
    parent_type_id_for_particle = None
    for rt in roi_types:
        if rt["name"] == roi_type_name:
            particle_type_id = rt["id"]
            parent_type_id_for_particle = rt["parent_type_id"]
            break
    if particle_type_id is None:
        raise ValueError(f"ROI type {roi_type_name!r} not found")

    # Get the parent ROI type — particles must have a parent
    if parent_type_id_for_particle is None:
        raise ValueError(
            f"ROI type {roi_type_name!r} has no parent_type_id — "
            f"cannot create sub-cellular particles"
        )

    # Get parent ROIs (cells) for this FOV
    parent_rois = store.db.get_rois_by_fov_and_type(
        fov_id, parent_type_id_for_particle
    )
    if not parent_rois:
        logger.info("No parent ROIs for fov — skipping particle analysis")
        return ParticleAnalysisResult(
            particles_created=0,
            particle_label_image=np.zeros((1, 1), dtype=np.int32),
            parent_rois_analyzed=0,
        )

    # Find active segmentation assignment to read labels
    assignments = store.db.get_active_assignments(fov_id)
    seg_assignments = assignments["segmentation"]
    seg_set_id = None
    for sa in seg_assignments:
        if sa["roi_type_id"] == parent_type_id_for_particle:
            seg_set_id = sa["segmentation_set_id"]
            break
    if seg_set_id is None:
        raise ValueError("No active segmentation assignment found for parent ROI type")

    # Read data
    fov_hex = uuid_to_hex(fov_id)
    seg_hex = uuid_to_hex(seg_set_id)
    mask_hex = uuid_to_hex(mask_id)

    labels = store.layers.read_labels(seg_hex, fov_hex)
    threshold_mask = store.layers.read_mask(mask_hex)
    threshold_bool = threshold_mask > 0

    # Full FOV particle label image
    particle_label_image = np.zeros(labels.shape, dtype=np.int32)
    next_particle_label = 1
    total_particles = 0

    for roi in parent_rois:
        parent_roi_id = roi["id"]
        label_val = roi["label_id"]
        by = roi["bbox_y"]
        bx = roi["bbox_x"]
        bh = roi["bbox_h"]
        bw = roi["bbox_w"]

        # Crop to bounding box
        label_crop = labels[by : by + bh, bx : bx + bw]
        mask_crop = threshold_bool[by : by + bh, bx : bx + bw]

        # Intersect: threshold mask AND cell mask
        cell_mask = label_crop == label_val
        particle_mask = mask_crop & cell_mask

        if not np.any(particle_mask):
            continue

        # Connected components
        cc_labels, n_cc = scipy_label(particle_mask)
        props = regionprops(cc_labels)

        for prop in props:
            if prop.area < min_particle_area:
                continue

            # Centroid in FOV coordinates
            cy_local, cx_local = prop.centroid
            # Bbox in FOV coordinates
            min_row, min_col, max_row, max_col = prop.bbox
            p_bbox_y = min_row + by
            p_bbox_x = min_col + bx
            p_bbox_h = max_row - min_row
            p_bbox_w = max_col - min_col

            # Create particle ROI
            particle_roi_id = new_uuid()
            store.db.insert_roi(
                id=particle_roi_id,
                fov_id=fov_id,
                roi_type_id=particle_type_id,
                cell_identity_id=None,  # Sub-cellular ROIs have no cell identity
                parent_roi_id=parent_roi_id,
                label_id=next_particle_label,
                bbox_y=p_bbox_y,
                bbox_x=p_bbox_x,
                bbox_h=p_bbox_h,
                bbox_w=p_bbox_w,
                area_px=int(prop.area),
            )

            # Write particle into FOV-level label image
            particle_label_image[by : by + bh, bx : bx + bw][
                cc_labels == prop.label
            ] = next_particle_label
            next_particle_label += 1
            total_particles += 1

    return ParticleAnalysisResult(
        particles_created=total_particles,
        particle_label_image=particle_label_image,
        parent_rois_analyzed=len(parent_rois),
    )
