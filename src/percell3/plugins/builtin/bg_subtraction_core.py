"""Background subtraction core algorithm — pure numpy/scipy, no store dependencies.

Ported from PerCell 1's ``_intensity_analysis_base.py`` with these changes:
- Uses numpy arrays instead of ImageJ ROIs
- Operates on particle label images instead of zip ROI files
- Channel-agnostic (no hardcoded PB/SG/Cap)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParticleBGResult:
    """Background subtraction result for a single particle.

    Attributes:
        particle_label: Label value of this particle in the particle label image.
        cell_id: Database cell ID this particle belongs to.
        area_pixels: Number of pixels in the particle mask.
        raw_mean_intensity: Mean intensity of the particle region (no bg sub).
        raw_integrated_intensity: Sum of intensities in the particle region.
        bg_estimate: Estimated background value from ring histogram.
        bg_ring_pixels: Number of pixels in the background ring.
        bg_sub_mean_intensity: Mean of (pixel - bg_estimate) across particle.
        bg_sub_integrated_intensity: Sum of (pixel - bg_estimate) across particle.
        peak_info: Histogram analysis details (for QC/visualization).
    """

    particle_label: int
    cell_id: int
    area_pixels: int
    raw_mean_intensity: float
    raw_integrated_intensity: float
    bg_estimate: float
    bg_ring_pixels: int
    bg_sub_mean_intensity: float
    bg_sub_integrated_intensity: float
    peak_info: dict | None = None


def estimate_background_gaussian(
    ring_intensities: np.ndarray,
    n_bins: int = 50,
    sigma: float = 2.0,
    max_background: float | None = None,
) -> tuple[float, dict] | None:
    """Estimate background from ring pixel histogram using Gaussian peak detection.

    Delegates to :func:`~percell3.plugins.builtin.peak_detection.find_gaussian_peaks`
    and wraps the result in the legacy ``(float, dict)`` format for backward
    compatibility with existing callers.

    Args:
        ring_intensities: 1D array of pixel intensities from the background ring.
        n_bins: Number of histogram bins.
        sigma: Gaussian smoothing sigma.
        max_background: If set, prefer the most prominent peak below this value.

    Returns:
        Tuple of (background_value, peak_info_dict), or None if input is empty.
    """
    from percell3.plugins.builtin.peak_detection import find_gaussian_peaks

    if len(ring_intensities) == 0:
        return None

    # Preserve legacy behavior: all-zeros returns (0.0, {...})
    if float(np.max(ring_intensities)) == 0:
        return 0.0, {
            "n_peaks": 0,
            "background_value": 0.0,
            "hist": np.zeros(n_bins),
            "bin_centers": np.zeros(n_bins),
            "hist_smooth": np.zeros(n_bins),
        }

    result = find_gaussian_peaks(
        ring_intensities,
        n_bins=n_bins,
        sigma=sigma,
        max_background=max_background,
    )

    if result is None:
        return None

    peak_info = {
        "n_peaks": result.n_peaks,
        "background_value": result.background_value,
        "hist": result.hist,
        "bin_centers": result.bin_centers,
        "hist_smooth": result.hist_smooth,
    }

    return result.background_value, peak_info


def compute_background_ring(
    particle_mask: np.ndarray,
    all_particles_mask: np.ndarray,
    exclusion_mask: np.ndarray | None,
    dilation_pixels: int,
) -> np.ndarray:
    """Create background ring by dilating a particle mask and subtracting exclusions.

    Steps:
    1. Dilate particle_mask by dilation_pixels using a disk structuring element.
    2. Ring = dilated AND NOT all_particles_mask (excludes all particles in cell).
    3. If exclusion_mask provided: ring = ring AND NOT exclusion_mask.

    Args:
        particle_mask: Boolean 2D mask for a single particle.
        all_particles_mask: Boolean 2D mask of ALL particles in this cell.
        exclusion_mask: Optional boolean 2D mask to exclude (e.g., another channel's particles).
        dilation_pixels: Number of pixels to dilate.

    Returns:
        Boolean 2D mask of the background ring.
    """
    from scipy.ndimage import binary_dilation
    from skimage.morphology import disk

    structuring_element = disk(dilation_pixels)
    dilated = binary_dilation(particle_mask, structure=structuring_element)

    # Ring = dilated region minus all particles in the cell
    ring = dilated & ~all_particles_mask

    # Subtract exclusion mask if provided
    if exclusion_mask is not None:
        ring = ring & ~exclusion_mask

    return ring


def process_particles_for_cell(
    cell_id: int,
    cell_mask: np.ndarray,
    particle_labels: np.ndarray,
    measurement_image: np.ndarray,
    exclusion_mask: np.ndarray | None,
    dilation_pixels: int,
    max_background: float | None = None,
) -> list[ParticleBGResult]:
    """Process all particles in a cell, computing per-particle background subtraction.

    For each particle in the cell:
    1. Extract its binary mask from particle_labels
    2. Compute background ring (dilate, exclude other particles + exclusion mask)
    3. Estimate background from ring histogram (Gaussian peak detection)
    4. Compute background-subtracted intensities

    Args:
        cell_id: Database cell ID.
        cell_mask: Boolean mask of the cell region within the crop.
        particle_labels: Integer label image (same shape as cell_mask crop).
            Pixel value = particle ID, 0 = background.
        measurement_image: Intensity image of the measurement channel (same crop).
        exclusion_mask: Optional boolean mask to exclude from ring computation.
        dilation_pixels: Ring dilation amount in pixels.
        max_background: Optional upper bound on background estimate.

    Returns:
        List of ParticleBGResult, one per particle with valid background ring.
    """
    results: list[ParticleBGResult] = []

    # Find unique particle labels (excluding 0 = background)
    unique_labels = np.unique(particle_labels)
    unique_labels = unique_labels[unique_labels != 0]

    if len(unique_labels) == 0:
        return results

    # Build combined mask of ALL particles in this cell (for ring exclusion)
    all_particles_mask = (particle_labels > 0) & cell_mask

    for label_val in unique_labels:
        particle_mask = (particle_labels == label_val) & cell_mask
        particle_pixels = int(np.sum(particle_mask))

        if particle_pixels == 0:
            continue

        # Compute background ring
        ring = compute_background_ring(
            particle_mask, all_particles_mask, exclusion_mask, dilation_pixels,
        )

        # Clip ring to within the cell region (optional: keeps ring local to cell)
        # Note: we intentionally do NOT clip to cell_mask — the ring extends
        # beyond the cell boundary to capture true local background.

        ring_pixels = int(np.sum(ring))

        if ring_pixels == 0:
            logger.debug(
                "Cell %d, particle %d: zero ring pixels after exclusion, skipping",
                cell_id, label_val,
            )
            results.append(ParticleBGResult(
                particle_label=int(label_val),
                cell_id=cell_id,
                area_pixels=particle_pixels,
                raw_mean_intensity=float(np.mean(measurement_image[particle_mask])),
                raw_integrated_intensity=float(np.sum(measurement_image[particle_mask].astype(np.float64))),
                bg_estimate=float("nan"),
                bg_ring_pixels=0,
                bg_sub_mean_intensity=float("nan"),
                bg_sub_integrated_intensity=float("nan"),
                peak_info=None,
            ))
            continue

        # Extract ring intensities and estimate background
        ring_intensities = measurement_image[ring].astype(np.float64)
        bg_result = estimate_background_gaussian(
            ring_intensities, max_background=max_background,
        )

        if bg_result is None:
            bg_value = 0.0
            peak_info = None
        else:
            bg_value, peak_info = bg_result

        # Compute raw and background-subtracted intensities for the particle
        particle_intensities = measurement_image[particle_mask].astype(np.float64)
        raw_mean = float(np.mean(particle_intensities))
        raw_integrated = float(np.sum(particle_intensities))

        bg_subtracted = particle_intensities - bg_value
        bg_sub_mean = float(np.mean(bg_subtracted))
        bg_sub_integrated = float(np.sum(bg_subtracted))

        results.append(ParticleBGResult(
            particle_label=int(label_val),
            cell_id=cell_id,
            area_pixels=particle_pixels,
            raw_mean_intensity=raw_mean,
            raw_integrated_intensity=raw_integrated,
            bg_estimate=bg_value,
            bg_ring_pixels=ring_pixels,
            bg_sub_mean_intensity=bg_sub_mean,
            bg_sub_integrated_intensity=bg_sub_integrated,
            peak_info=peak_info,
        ))

    return results
