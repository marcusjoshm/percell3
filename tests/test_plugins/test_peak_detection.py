"""Tests for peak_detection module — pure numpy/scipy functions."""

from __future__ import annotations

import numpy as np
import pytest

from percell3.plugins.builtin.peak_detection import (
    PeakDetectionResult,
    find_gaussian_peaks,
    render_peak_histogram,
)


class TestFindGaussianPeaks:
    """Tests for histogram-based peak detection."""

    def test_empty_array_returns_none(self) -> None:
        result = find_gaussian_peaks(np.array([]))
        assert result is None

    def test_all_zeros_returns_none(self) -> None:
        """All-zero data has no non-zero pixels, returns None."""
        result = find_gaussian_peaks(np.zeros(100))
        assert result is None

    def test_single_peak_detects_background(self) -> None:
        rng = np.random.default_rng(42)
        data = rng.normal(loc=50, scale=5, size=1000).clip(1, 200)
        result = find_gaussian_peaks(data)

        assert result is not None
        assert isinstance(result, PeakDetectionResult)
        assert 35 <= result.background_value <= 65
        assert result.n_peaks >= 1

    def test_two_peaks_picks_most_prominent(self) -> None:
        """With two populations, the most prominent peak is selected."""
        rng = np.random.default_rng(42)
        # Large background population (most prominent)
        bg_pop = rng.normal(loc=30, scale=5, size=2000).clip(1, 200)
        # Smaller signal population
        signal_pop = rng.normal(loc=120, scale=10, size=500).clip(1, 200)
        data = np.concatenate([bg_pop, signal_pop])

        result = find_gaussian_peaks(data)
        assert result is not None
        # Background peak is most prominent (more data points)
        assert 20 <= result.background_value <= 45
        assert result.n_peaks >= 2

    def test_max_background_prefers_peak_below_threshold(self) -> None:
        rng = np.random.default_rng(42)
        low_pop = rng.normal(loc=30, scale=5, size=500).clip(1, 200)
        high_pop = rng.normal(loc=150, scale=10, size=2000).clip(1, 300)
        data = np.concatenate([low_pop, high_pop])

        result = find_gaussian_peaks(data, max_background=80.0)
        assert result is not None
        assert result.background_value < 80.0

    def test_returns_peak_detection_result(self) -> None:
        rng = np.random.default_rng(42)
        data = rng.normal(loc=100, scale=15, size=500).clip(1, 255)

        result = find_gaussian_peaks(data, n_bins=30)
        assert result is not None
        assert isinstance(result, PeakDetectionResult)
        assert isinstance(result.background_value, float)
        assert isinstance(result.n_peaks, int)
        assert len(result.hist) == 30
        assert len(result.bin_centers) == 30
        assert len(result.hist_smooth) == 30

    def test_custom_n_bins(self) -> None:
        rng = np.random.default_rng(42)
        data = rng.normal(loc=50, scale=10, size=500).clip(1, 200)

        result = find_gaussian_peaks(data, n_bins=100)
        assert result is not None
        assert len(result.hist) == 100

    def test_returns_float_background(self) -> None:
        rng = np.random.default_rng(42)
        data = rng.poisson(lam=50, size=1000).astype(np.float64)
        data = data[data > 0]  # ensure non-zero

        result = find_gaussian_peaks(data)
        assert result is not None
        assert isinstance(result.background_value, float)
        assert result.background_value > 0

    def test_single_nonzero_value(self) -> None:
        """A single non-zero value should return that value's bin."""
        data = np.array([100.0])
        result = find_gaussian_peaks(data)
        assert result is not None
        assert result.background_value > 0

    def test_no_peaks_falls_back_to_argmax(self) -> None:
        """Uniform-ish data may have no prominent peaks; should use argmax."""
        rng = np.random.default_rng(42)
        data = rng.uniform(10, 200, size=500)
        result = find_gaussian_peaks(data)
        assert result is not None
        assert result.background_value > 0

    def test_frozen_dataclass(self) -> None:
        """PeakDetectionResult should be immutable."""
        rng = np.random.default_rng(42)
        data = rng.normal(loc=50, scale=5, size=500).clip(1, 200)
        result = find_gaussian_peaks(data)
        assert result is not None
        with pytest.raises(AttributeError):
            result.background_value = 999.0  # type: ignore[misc]


class TestRenderPeakHistogram:
    """Tests for histogram PNG rendering."""

    def test_creates_png_file(self, tmp_path) -> None:
        rng = np.random.default_rng(42)
        data = rng.normal(loc=50, scale=5, size=500).clip(1, 200)
        result = find_gaussian_peaks(data)
        assert result is not None

        output_path = tmp_path / "hist.png"
        render_peak_histogram(result, "Test Histogram", output_path)
        assert output_path.exists()
        assert output_path.stat().st_size > 0

    def test_creates_parent_directories(self, tmp_path) -> None:
        rng = np.random.default_rng(42)
        data = rng.normal(loc=50, scale=5, size=500).clip(1, 200)
        result = find_gaussian_peaks(data)
        assert result is not None

        output_path = tmp_path / "subdir" / "nested" / "hist.png"
        render_peak_histogram(result, "Nested Test", output_path)
        assert output_path.exists()

    def test_handles_single_bin_center(self, tmp_path) -> None:
        """Edge case: result with very few data points."""
        result = PeakDetectionResult(
            background_value=50.0,
            n_peaks=1,
            hist=np.array([10.0]),
            bin_centers=np.array([50.0]),
            hist_smooth=np.array([10.0]),
            peak_indices=np.array([0], dtype=np.intp),
        )
        output_path = tmp_path / "single_bin.png"
        render_peak_histogram(result, "Single Bin", output_path)
        assert output_path.exists()
