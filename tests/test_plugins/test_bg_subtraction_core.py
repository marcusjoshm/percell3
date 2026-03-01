"""Tests for background subtraction core algorithm — pure numpy/scipy functions."""

from __future__ import annotations

import numpy as np
import pytest

from percell3.plugins.builtin.bg_subtraction_core import (
    ParticleBGResult,
    compute_background_ring,
    estimate_background_gaussian,
    process_particles_for_cell,
)


# ---------------------------------------------------------------------------
# estimate_background_gaussian
# ---------------------------------------------------------------------------


class TestEstimateBackgroundGaussian:
    """Tests for Gaussian peak-based background estimation."""

    def test_empty_array_returns_none(self) -> None:
        result = estimate_background_gaussian(np.array([]))
        assert result is None

    def test_all_zeros_returns_zero(self) -> None:
        data = np.zeros(100)
        bg_value, info = estimate_background_gaussian(data)
        assert bg_value == 0.0
        assert info["n_peaks"] == 0

    def test_single_peak_detects_background(self) -> None:
        """A tight cluster of values should produce a single-peak background estimate."""
        rng = np.random.default_rng(42)
        # Background at ~50, small spread
        data = rng.normal(loc=50, scale=5, size=1000).clip(0, 200)
        bg_value, info = estimate_background_gaussian(data)
        # Should be close to 50
        assert 40 <= bg_value <= 60
        assert info["n_peaks"] >= 1

    def test_two_peaks_picks_lowest(self) -> None:
        """With two populations, the lowest-position peak is background."""
        rng = np.random.default_rng(42)
        bg_pop = rng.normal(loc=30, scale=5, size=2000)
        signal_pop = rng.normal(loc=120, scale=10, size=500)
        data = np.concatenate([bg_pop, signal_pop]).clip(0, 200)

        bg_value, info = estimate_background_gaussian(data)
        # Should pick the background peak (~30), not the signal peak (~120)
        assert 20 <= bg_value <= 45
        assert info["n_peaks"] >= 2

    def test_max_background_prefers_peak_below_threshold(self) -> None:
        """max_background should prefer the most prominent peak below that value."""
        rng = np.random.default_rng(42)
        low_pop = rng.normal(loc=30, scale=5, size=500)
        high_pop = rng.normal(loc=150, scale=10, size=2000)
        data = np.concatenate([low_pop, high_pop]).clip(0, 300)

        bg_value, info = estimate_background_gaussian(data, max_background=80.0)
        # Should prefer peak near 30, not 150
        assert bg_value < 80.0

    def test_max_background_fallback_when_no_peaks_below(self) -> None:
        """If all peaks are above max_background, falls back gracefully."""
        rng = np.random.default_rng(42)
        data = rng.normal(loc=200, scale=10, size=1000).clip(100, 300)

        bg_value, info = estimate_background_gaussian(data, max_background=50.0)
        # Should still return a value (fallback behavior)
        assert isinstance(bg_value, float)
        assert not np.isnan(bg_value)

    def test_peak_info_contains_histogram_data(self) -> None:
        """Returned peak_info should contain histogram arrays for QC."""
        rng = np.random.default_rng(42)
        data = rng.normal(loc=100, scale=15, size=500).clip(0, 255)

        bg_value, info = estimate_background_gaussian(data, n_bins=30)
        assert "hist" in info
        assert "bin_centers" in info
        assert "hist_smooth" in info
        assert len(info["hist"]) == 30
        assert len(info["bin_centers"]) == 30

    def test_custom_n_bins(self) -> None:
        rng = np.random.default_rng(42)
        data = rng.normal(loc=50, scale=10, size=500).clip(0, 200)
        _, info = estimate_background_gaussian(data, n_bins=100)
        assert len(info["hist"]) == 100

    def test_returns_float_from_bin_center(self) -> None:
        """Background estimate is the Gaussian peak bin center (a float)."""
        rng = np.random.default_rng(42)
        data = rng.poisson(lam=50, size=1000).astype(np.float64)
        bg_value, _ = estimate_background_gaussian(data)
        assert isinstance(bg_value, float)
        assert bg_value > 0


# ---------------------------------------------------------------------------
# compute_background_ring
# ---------------------------------------------------------------------------


class TestComputeBackgroundRing:
    """Tests for background ring computation via dilation."""

    def _make_small_image(self, size: int = 50) -> np.ndarray:
        return np.zeros((size, size), dtype=bool)

    def test_basic_ring_around_particle(self) -> None:
        """Dilating a central dot should produce a ring around it."""
        particle_mask = self._make_small_image()
        particle_mask[25, 25] = True

        all_particles_mask = particle_mask.copy()

        ring = compute_background_ring(particle_mask, all_particles_mask, None, dilation_pixels=3)

        # Ring should have pixels but not at the particle location
        assert np.sum(ring) > 0
        assert not ring[25, 25]  # particle itself excluded

    def test_ring_excludes_all_particles(self) -> None:
        """Ring should not overlap any particle in the cell."""
        particle_mask = self._make_small_image()
        particle_mask[20, 20] = True

        # Another particle nearby
        all_particles_mask = self._make_small_image()
        all_particles_mask[20, 20] = True
        all_particles_mask[22, 22] = True

        ring = compute_background_ring(particle_mask, all_particles_mask, None, dilation_pixels=5)

        # Ring must not include any particle pixels
        overlap = ring & all_particles_mask
        assert np.sum(overlap) == 0

    def test_ring_excludes_exclusion_mask(self) -> None:
        """Exclusion mask regions should be removed from ring."""
        particle_mask = self._make_small_image()
        particle_mask[25, 25] = True

        all_particles_mask = particle_mask.copy()

        exclusion_mask = self._make_small_image()
        exclusion_mask[23:28, 23:28] = True  # block area around particle

        ring = compute_background_ring(particle_mask, all_particles_mask, exclusion_mask, dilation_pixels=5)

        # No ring pixels where exclusion mask is True
        overlap = ring & exclusion_mask
        assert np.sum(overlap) == 0

    def test_no_exclusion_mask(self) -> None:
        """With exclusion_mask=None, ring should still be valid."""
        particle_mask = self._make_small_image()
        particle_mask[25, 25] = True
        all_particles_mask = particle_mask.copy()

        ring = compute_background_ring(particle_mask, all_particles_mask, None, dilation_pixels=3)
        assert np.sum(ring) > 0

    def test_ring_at_image_edge(self) -> None:
        """Particle near edge should produce a clipped ring without errors."""
        particle_mask = self._make_small_image(size=30)
        particle_mask[0, 0] = True
        all_particles_mask = particle_mask.copy()

        ring = compute_background_ring(particle_mask, all_particles_mask, None, dilation_pixels=5)
        # Should not raise; ring may be smaller than usual
        assert ring.shape == (30, 30)
        assert np.sum(ring) > 0

    def test_large_dilation(self) -> None:
        """Large dilation should produce a large ring."""
        particle_mask = self._make_small_image()
        particle_mask[25, 25] = True
        all_particles_mask = particle_mask.copy()

        small_ring = compute_background_ring(particle_mask, all_particles_mask, None, dilation_pixels=3)
        large_ring = compute_background_ring(particle_mask, all_particles_mask, None, dilation_pixels=10)

        assert np.sum(large_ring) > np.sum(small_ring)


# ---------------------------------------------------------------------------
# process_particles_for_cell
# ---------------------------------------------------------------------------


class TestProcessParticlesForCell:
    """Tests for the full per-cell particle processing pipeline."""

    def _make_synthetic_cell(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Create a synthetic cell with two particles and a measurement image.

        Returns:
            (cell_mask, particle_labels, measurement_image)
        """
        size = 60
        cell_mask = np.zeros((size, size), dtype=bool)
        cell_mask[5:55, 5:55] = True  # large cell

        particle_labels = np.zeros((size, size), dtype=np.int32)
        # Particle 1: small blob at (20, 20)
        particle_labels[18:23, 18:23] = 1
        # Particle 2: small blob at (40, 40)
        particle_labels[38:43, 38:43] = 2

        # Measurement image: background ~50, particles ~200
        rng = np.random.default_rng(42)
        measurement = rng.normal(loc=50, scale=5, size=(size, size)).clip(0, 65535)
        measurement[18:23, 18:23] = rng.normal(loc=200, scale=10, size=(5, 5)).clip(0, 65535)
        measurement[38:43, 38:43] = rng.normal(loc=200, scale=10, size=(5, 5)).clip(0, 65535)
        measurement = measurement.astype(np.uint16)

        return cell_mask, particle_labels, measurement

    def test_basic_processing(self) -> None:
        """Should produce one result per particle."""
        cell_mask, particle_labels, measurement = self._make_synthetic_cell()

        results = process_particles_for_cell(
            cell_id=1,
            cell_mask=cell_mask,
            particle_labels=particle_labels,
            measurement_image=measurement,
            exclusion_mask=None,
            dilation_pixels=5,
        )

        assert len(results) == 2
        assert all(isinstance(r, ParticleBGResult) for r in results)
        labels = {r.particle_label for r in results}
        assert labels == {1, 2}

    def test_results_have_valid_fields(self) -> None:
        cell_mask, particle_labels, measurement = self._make_synthetic_cell()

        results = process_particles_for_cell(
            cell_id=42,
            cell_mask=cell_mask,
            particle_labels=particle_labels,
            measurement_image=measurement,
            exclusion_mask=None,
            dilation_pixels=5,
        )

        for r in results:
            assert r.cell_id == 42
            assert r.area_pixels > 0
            assert r.raw_mean_intensity > 0
            assert r.raw_integrated_intensity > 0
            assert r.bg_ring_pixels > 0
            assert not np.isnan(r.bg_estimate)
            # bg_sub_mean should be positive for bright particles on dim background
            assert r.bg_sub_mean_intensity > 0

    def test_background_subtraction_reduces_intensity(self) -> None:
        """BG-subtracted mean should be lower than raw mean."""
        cell_mask, particle_labels, measurement = self._make_synthetic_cell()

        results = process_particles_for_cell(
            cell_id=1,
            cell_mask=cell_mask,
            particle_labels=particle_labels,
            measurement_image=measurement,
            exclusion_mask=None,
            dilation_pixels=5,
        )

        for r in results:
            assert r.bg_sub_mean_intensity < r.raw_mean_intensity

    def test_no_particles_returns_empty(self) -> None:
        """If particle_labels is all zeros, return empty list."""
        cell_mask = np.ones((30, 30), dtype=bool)
        particle_labels = np.zeros((30, 30), dtype=np.int32)
        measurement = np.ones((30, 30), dtype=np.uint16) * 100

        results = process_particles_for_cell(
            cell_id=1,
            cell_mask=cell_mask,
            particle_labels=particle_labels,
            measurement_image=measurement,
            exclusion_mask=None,
            dilation_pixels=5,
        )

        assert results == []

    def test_with_exclusion_mask(self) -> None:
        """Exclusion mask should affect the ring but not crash."""
        cell_mask, particle_labels, measurement = self._make_synthetic_cell()

        # Exclusion mask covers a region
        exclusion_mask = np.zeros_like(cell_mask)
        exclusion_mask[15:25, 15:25] = True

        results = process_particles_for_cell(
            cell_id=1,
            cell_mask=cell_mask,
            particle_labels=particle_labels,
            measurement_image=measurement,
            exclusion_mask=exclusion_mask,
            dilation_pixels=5,
        )

        assert len(results) == 2

    def test_zero_ring_pixels_produces_nan(self) -> None:
        """If ring is completely blocked, result should have NaN bg values."""
        size = 10
        cell_mask = np.ones((size, size), dtype=bool)
        particle_labels = np.zeros((size, size), dtype=np.int32)
        # One particle fills most of the image
        particle_labels[1:9, 1:9] = 1

        measurement = np.ones((size, size), dtype=np.uint16) * 100

        # Exclusion mask blocks everything the ring could reach
        exclusion_mask = np.ones((size, size), dtype=bool)

        results = process_particles_for_cell(
            cell_id=1,
            cell_mask=cell_mask,
            particle_labels=particle_labels,
            measurement_image=measurement,
            exclusion_mask=exclusion_mask,
            dilation_pixels=2,
        )

        assert len(results) == 1
        r = results[0]
        assert np.isnan(r.bg_estimate)
        assert np.isnan(r.bg_sub_mean_intensity)
        assert np.isnan(r.bg_sub_integrated_intensity)
        assert r.bg_ring_pixels == 0
        # Raw values should still be valid
        assert r.raw_mean_intensity == 100.0
        assert r.area_pixels > 0

    def test_max_background_parameter(self) -> None:
        """max_background should be passed through to the estimator."""
        cell_mask, particle_labels, measurement = self._make_synthetic_cell()

        results = process_particles_for_cell(
            cell_id=1,
            cell_mask=cell_mask,
            particle_labels=particle_labels,
            measurement_image=measurement,
            exclusion_mask=None,
            dilation_pixels=5,
            max_background=100.0,
        )

        for r in results:
            assert r.bg_estimate <= 100.0

    def test_particle_outside_cell_mask_ignored(self) -> None:
        """Particles outside the cell mask should have zero pixel count and be skipped."""
        size = 40
        cell_mask = np.zeros((size, size), dtype=bool)
        cell_mask[0:20, 0:20] = True  # cell in top-left

        particle_labels = np.zeros((size, size), dtype=np.int32)
        particle_labels[30:35, 30:35] = 1  # particle in bottom-right, outside cell

        measurement = np.ones((size, size), dtype=np.uint16) * 100

        results = process_particles_for_cell(
            cell_id=1,
            cell_mask=cell_mask,
            particle_labels=particle_labels,
            measurement_image=measurement,
            exclusion_mask=None,
            dilation_pixels=5,
        )

        # Particle is outside cell mask → masked to zero pixels → skipped
        assert results == []
