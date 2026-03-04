"""Histogram-based peak detection for background estimation.

Pure numpy/scipy module with no store dependencies. Shared by background
subtraction plugins that need to estimate background from intensity histograms.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt


@dataclass(frozen=True, slots=True)
class PeakDetectionResult:
    """Result of histogram-based background estimation.

    Attributes:
        background_value: Estimated background intensity value.
        n_peaks: Number of prominent peaks detected in the histogram.
        hist: Raw histogram counts.
        bin_centers: Bin center values for the histogram.
        hist_smooth: Gaussian-smoothed histogram.
        peak_indices: Indices into bin_centers of detected peaks.
    """

    background_value: float
    n_peaks: int
    hist: npt.NDArray[np.float64]
    bin_centers: npt.NDArray[np.float64]
    hist_smooth: npt.NDArray[np.float64]
    peak_indices: npt.NDArray[np.intp]


def find_gaussian_peaks(
    data: npt.NDArray[np.number],
    n_bins: int = 50,
    sigma: float = 2.0,
    min_prominence_frac: float = 0.15,
    max_background: float | None = None,
) -> PeakDetectionResult | None:
    """Estimate background value from intensity histogram peak detection.

    Algorithm:
    1. Filter out zero-valued pixels.
    2. Build histogram over (0, max_value).
    3. Smooth with 1D Gaussian filter.
    4. Detect peaks with minimum prominence threshold.
    5. Select background peak (most prominent below max_background, or leftmost).

    Args:
        data: 1D array of pixel intensities (zeros are filtered out internally).
        n_bins: Number of histogram bins.
        sigma: Gaussian smoothing sigma for the histogram.
        min_prominence_frac: Minimum peak prominence as fraction of max.
        max_background: If set, prefer the most prominent peak below this value.

    Returns:
        PeakDetectionResult with background value and histogram data for
        diagnostic plotting, or None if no valid (non-zero) data.
    """
    from scipy.ndimage import gaussian_filter1d
    from scipy.signal import find_peaks

    # Filter out zeros
    data = data[data > 0]
    if len(data) == 0:
        return None

    data_max = float(np.max(data))

    hist, bin_edges = np.histogram(data, bins=n_bins, range=(0, data_max))
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
    hist_smooth = gaussian_filter1d(hist.astype(np.float64), sigma=sigma)

    min_prominence = float(np.max(hist_smooth)) * min_prominence_frac
    peaks, properties = find_peaks(hist_smooth, prominence=min_prominence)

    if len(peaks) == 0:
        # No prominent peaks — use argmax of smoothed histogram
        peak_idx = int(np.argmax(hist_smooth))
        return PeakDetectionResult(
            background_value=float(bin_centers[peak_idx]),
            n_peaks=1,
            hist=hist.astype(np.float64),
            bin_centers=bin_centers,
            hist_smooth=hist_smooth,
            peak_indices=np.array([peak_idx], dtype=np.intp),
        )

    peak_positions = bin_centers[peaks]
    peak_prominences = properties["prominences"]

    if max_background is not None:
        peaks_below = peak_positions < max_background
        if np.any(peaks_below):
            prominences_below = peak_prominences[peaks_below]
            positions_below = peak_positions[peaks_below]
            most_prominent_idx = int(np.argmax(prominences_below))
            background_value = float(positions_below[most_prominent_idx])
        else:
            bins_below = bin_centers < max_background
            if np.any(bins_below):
                hist_below = hist[bins_below]
                centers_below = bin_centers[bins_below]
                background_value = float(centers_below[int(np.argmax(hist_below))])
            else:
                sorted_by_pos = np.argsort(peak_positions)
                background_value = float(peak_positions[sorted_by_pos[0]])
    else:
        # Most prominent peak = background estimate
        most_prominent_idx = int(np.argmax(peak_prominences))
        background_value = float(peak_positions[most_prominent_idx])

    return PeakDetectionResult(
        background_value=background_value,
        n_peaks=len(peaks),
        hist=hist.astype(np.float64),
        bin_centers=bin_centers,
        hist_smooth=hist_smooth,
        peak_indices=peaks.astype(np.intp),
    )


def render_peak_histogram(
    result: PeakDetectionResult,
    title: str,
    output_path: Path,
) -> None:
    """Save diagnostic histogram PNG showing detected background peak.

    Args:
        result: Peak detection result with histogram data.
        title: Plot title (e.g., "FOV_1 / threshold_g1 / DAPI").
        output_path: Path to save the PNG file.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6, 4))
    try:
        bin_width = (
            float(result.bin_centers[1] - result.bin_centers[0])
            if len(result.bin_centers) > 1
            else 1.0
        )
        ax.bar(
            result.bin_centers, result.hist,
            width=bin_width, alpha=0.5, color="steelblue", label="Raw",
        )
        ax.plot(result.bin_centers, result.hist_smooth, "r-", linewidth=1.5, label="Smoothed")
        ax.axvline(
            result.background_value, color="green", linestyle="--", linewidth=1.5,
            label=f"BG = {result.background_value:.1f}",
        )
        ax.set_xlabel("Intensity")
        ax.set_ylabel("Count")
        ax.set_title(title)
        ax.legend()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=100, bbox_inches="tight")
    finally:
        plt.close(fig)
