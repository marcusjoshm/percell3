"""ParticleAnalyzer — connected component analysis within threshold masks."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from percell3.core.models import MeasurementRecord, ParticleRecord

if TYPE_CHECKING:
    from percell3.core import ExperimentStore

logger = logging.getLogger(__name__)

PARTICLE_SUMMARY_METRICS = [
    "particle_count",
    "total_particle_area",
    "mean_particle_area",
    "max_particle_area",
    "particle_coverage_fraction",
    "mean_particle_mean_intensity",
    "mean_particle_integrated_intensity",
    "total_particle_integrated_intensity",
]


@dataclass(frozen=True)
class ParticleAnalysisResult:
    """Result of particle analysis for a FOV.

    Attributes:
        threshold_run_id: ID of the threshold run analyzed.
        particles: List of ParticleRecord objects.
        summary_measurements: Per-cell summary MeasurementRecords.
        particle_label_image: Full FOV int32 label image with unique particle IDs.
        cells_analyzed: Number of cells processed.
        total_particles: Total particles found across all cells.
    """

    threshold_run_id: int
    particles: list[ParticleRecord]
    summary_measurements: list[MeasurementRecord]
    particle_label_image: np.ndarray
    cells_analyzed: int
    total_particles: int


class ParticleAnalyzer:
    """Detect and measure particles within threshold masks.

    For each cell, intersects the threshold mask with the cell's label region,
    finds connected components, and computes full morphometric properties.

    Args:
        min_particle_area: Minimum area in pixels to keep a particle (default: 5).
    """

    def __init__(self, min_particle_area: int = 5) -> None:
        self._min_area = min_particle_area

    def analyze_fov(
        self,
        store: ExperimentStore,
        fov: str,
        condition: str,
        channel: str,
        threshold_run_id: int,
        cell_ids: list[int],
        bio_rep: str | None = None,
        timepoint: str | None = None,
    ) -> ParticleAnalysisResult:
        """Analyze particles within threshold mask for cells in a FOV.

        For each cell:
        1. Crop label + threshold mask to cell bbox
        2. Intersect: particle_mask = threshold_mask AND (label == cell_label)
        3. Find connected components
        4. Filter by min_particle_area
        5. Measure morphometrics
        6. Build ParticleRecord + summary MeasurementRecords

        Args:
            store: Target ExperimentStore.
            fov: FOV name.
            condition: Condition name.
            channel: Channel used for thresholding.
            threshold_run_id: Which threshold run to analyze.
            cell_ids: Cell IDs to analyze (typically one group).
            bio_rep: Biological replicate name.
            timepoint: Timepoint.

        Returns:
            ParticleAnalysisResult with particles, summaries, and label image.
        """
        from scipy.ndimage import label as scipy_label
        from skimage.measure import regionprops

        # Read data
        labels = store.read_labels(fov, condition, bio_rep=bio_rep, timepoint=timepoint)
        threshold_mask = store.read_mask(fov, condition, channel, timepoint=timepoint)
        channel_image = store.read_image_numpy(
            fov, condition, channel, bio_rep=bio_rep, timepoint=timepoint,
        )

        # Convert mask: uint8 (0/255) -> bool
        threshold_bool = threshold_mask > 0

        # Get cells DataFrame
        cells_df = store.get_cells(
            condition=condition, bio_rep=bio_rep, fov=fov, timepoint=timepoint,
        )
        cells_df = cells_df[cells_df["id"].isin(cell_ids)]

        ch_info = store.get_channel(channel)
        channel_id = ch_info.id

        # Get pixel size for area conversion
        fov_info = store.get_fovs(condition=condition, bio_rep=bio_rep)
        fov_row = [f for f in fov_info if f.name == fov]
        pixel_size_um = fov_row[0].pixel_size_um if fov_row else None

        # Full FOV particle label image
        particle_label_image = np.zeros(labels.shape, dtype=np.int32)
        next_particle_id = 1

        all_particles: list[ParticleRecord] = []
        all_summaries: list[MeasurementRecord] = []

        for _, cell in cells_df.iterrows():
            cell_id = int(cell["id"])
            label_val = int(cell["label_value"])
            bx = int(cell["bbox_x"])
            by = int(cell["bbox_y"])
            bw = int(cell["bbox_w"])
            bh = int(cell["bbox_h"])
            cell_area = float(cell["area_pixels"])

            # Crop to bounding box
            label_crop = labels[by:by + bh, bx:bx + bw]
            mask_crop = threshold_bool[by:by + bh, bx:bx + bw]
            image_crop = channel_image[by:by + bh, bx:bx + bw]

            # Intersect: threshold mask AND cell mask
            cell_mask = label_crop == label_val
            particle_mask = mask_crop & cell_mask

            if not np.any(particle_mask):
                # No particles — record zero counts
                all_summaries.extend(
                    self._zero_summaries(cell_id, channel_id)
                )
                continue

            # Connected components
            cc_labels, n_cc = scipy_label(particle_mask)
            props = regionprops(cc_labels, intensity_image=image_crop)

            cell_particles: list[ParticleRecord] = []
            for prop in props:
                if prop.area < self._min_area:
                    continue

                # Compute morphometrics
                area_um2 = None
                if pixel_size_um:
                    area_um2 = float(prop.area) * (pixel_size_um ** 2)

                perimeter = float(prop.perimeter) if hasattr(prop, "perimeter") else None
                circularity = None
                if perimeter and perimeter > 0:
                    circularity = 4 * np.pi * prop.area / (perimeter ** 2)

                # Centroid in FOV coordinates
                cy_local, cx_local = prop.centroid
                centroid_x = cx_local + bx
                centroid_y = cy_local + by

                # Bbox in FOV coordinates
                min_row, min_col, max_row, max_col = prop.bbox
                p_bbox_x = min_col + bx
                p_bbox_y = min_row + by
                p_bbox_w = max_col - min_col
                p_bbox_h = max_row - min_row

                particle = ParticleRecord(
                    cell_id=cell_id,
                    threshold_run_id=threshold_run_id,
                    label_value=next_particle_id,
                    centroid_x=float(centroid_x),
                    centroid_y=float(centroid_y),
                    bbox_x=int(p_bbox_x),
                    bbox_y=int(p_bbox_y),
                    bbox_w=int(p_bbox_w),
                    bbox_h=int(p_bbox_h),
                    area_pixels=float(prop.area),
                    area_um2=area_um2,
                    perimeter=perimeter,
                    circularity=circularity,
                    eccentricity=float(prop.eccentricity) if hasattr(prop, "eccentricity") else None,
                    solidity=float(prop.solidity) if hasattr(prop, "solidity") else None,
                    major_axis_length=float(prop.axis_major_length),
                    minor_axis_length=float(prop.axis_minor_length),
                    mean_intensity=float(prop.intensity_mean),
                    max_intensity=float(np.max(image_crop[cc_labels == prop.label])),
                    integrated_intensity=float(np.sum(image_crop[cc_labels == prop.label])),
                )
                cell_particles.append(particle)

                # Write particle ID into FOV-level label image
                particle_label_image[by:by + bh, bx:bx + bw][
                    cc_labels == prop.label
                ] = next_particle_id
                next_particle_id += 1

            all_particles.extend(cell_particles)

            # Per-cell summaries
            all_summaries.extend(
                self._cell_summaries(cell_id, channel_id, cell_particles, cell_area)
            )

        return ParticleAnalysisResult(
            threshold_run_id=threshold_run_id,
            particles=all_particles,
            summary_measurements=all_summaries,
            particle_label_image=particle_label_image,
            cells_analyzed=len(cells_df),
            total_particles=len(all_particles),
        )

    def _zero_summaries(
        self, cell_id: int, channel_id: int,
    ) -> list[MeasurementRecord]:
        """Create summary measurements for a cell with no particles."""
        return [
            MeasurementRecord(cell_id=cell_id, channel_id=channel_id, metric="particle_count", value=0.0),
            MeasurementRecord(cell_id=cell_id, channel_id=channel_id, metric="total_particle_area", value=0.0),
            MeasurementRecord(cell_id=cell_id, channel_id=channel_id, metric="mean_particle_area", value=0.0),
            MeasurementRecord(cell_id=cell_id, channel_id=channel_id, metric="max_particle_area", value=0.0),
            MeasurementRecord(cell_id=cell_id, channel_id=channel_id, metric="particle_coverage_fraction", value=0.0),
            MeasurementRecord(cell_id=cell_id, channel_id=channel_id, metric="mean_particle_mean_intensity", value=0.0),
            MeasurementRecord(cell_id=cell_id, channel_id=channel_id, metric="mean_particle_integrated_intensity", value=0.0),
            MeasurementRecord(cell_id=cell_id, channel_id=channel_id, metric="total_particle_integrated_intensity", value=0.0),
        ]

    def _cell_summaries(
        self,
        cell_id: int,
        channel_id: int,
        particles: list[ParticleRecord],
        cell_area: float,
    ) -> list[MeasurementRecord]:
        """Create summary measurements for a cell's particles."""
        if not particles:
            return self._zero_summaries(cell_id, channel_id)

        areas = [p.area_pixels for p in particles]
        total_area = sum(areas)
        coverage = total_area / cell_area if cell_area > 0 else 0.0

        intensities_mean = [p.mean_intensity for p in particles if p.mean_intensity is not None]
        intensities_integ = [p.integrated_intensity for p in particles if p.integrated_intensity is not None]

        return [
            MeasurementRecord(cell_id=cell_id, channel_id=channel_id, metric="particle_count", value=float(len(particles))),
            MeasurementRecord(cell_id=cell_id, channel_id=channel_id, metric="total_particle_area", value=float(total_area)),
            MeasurementRecord(cell_id=cell_id, channel_id=channel_id, metric="mean_particle_area", value=float(np.mean(areas))),
            MeasurementRecord(cell_id=cell_id, channel_id=channel_id, metric="max_particle_area", value=float(max(areas))),
            MeasurementRecord(cell_id=cell_id, channel_id=channel_id, metric="particle_coverage_fraction", value=float(coverage)),
            MeasurementRecord(cell_id=cell_id, channel_id=channel_id, metric="mean_particle_mean_intensity", value=float(np.mean(intensities_mean)) if intensities_mean else 0.0),
            MeasurementRecord(cell_id=cell_id, channel_id=channel_id, metric="mean_particle_integrated_intensity", value=float(np.mean(intensities_integ)) if intensities_integ else 0.0),
            MeasurementRecord(cell_id=cell_id, channel_id=channel_id, metric="total_particle_integrated_intensity", value=float(sum(intensities_integ)) if intensities_integ else 0.0),
        ]
