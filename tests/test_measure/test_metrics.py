"""Tests for MetricRegistry and built-in metric functions."""

from __future__ import annotations

import numpy as np
import pytest

from percell3.measure.metrics import (
    MetricRegistry,
    area,
    integrated_intensity,
    max_intensity,
    mean_intensity,
    median_intensity,
    min_intensity,
    std_intensity,
)


# --- Built-in metric function tests (pure, no DB) ---


class TestBuiltinMetrics:
    """Test each built-in metric function directly."""

    @pytest.fixture
    def image_and_mask(self):
        """A 4x4 image with a known mask selecting specific pixels."""
        image = np.array([
            [10, 20, 30, 40],
            [50, 60, 70, 80],
            [90, 100, 110, 120],
            [130, 140, 150, 160],
        ], dtype=np.float64)
        # Mask selects a 2x2 block: values 60, 70, 100, 110
        mask = np.zeros((4, 4), dtype=bool)
        mask[1:3, 1:3] = True
        return image, mask

    def test_mean_intensity(self, image_and_mask):
        image, mask = image_and_mask
        result = mean_intensity(image, mask)
        assert result == pytest.approx(85.0)  # (60+70+100+110)/4

    def test_max_intensity(self, image_and_mask):
        image, mask = image_and_mask
        assert max_intensity(image, mask) == 110.0

    def test_min_intensity(self, image_and_mask):
        image, mask = image_and_mask
        assert min_intensity(image, mask) == 60.0

    def test_integrated_intensity(self, image_and_mask):
        image, mask = image_and_mask
        assert integrated_intensity(image, mask) == 340.0  # 60+70+100+110

    def test_std_intensity(self, image_and_mask):
        image, mask = image_and_mask
        expected = float(np.std([60, 70, 100, 110]))
        assert std_intensity(image, mask) == pytest.approx(expected)

    def test_median_intensity(self, image_and_mask):
        image, mask = image_and_mask
        assert median_intensity(image, mask) == pytest.approx(85.0)  # median of [60,70,100,110]

    def test_area(self, image_and_mask):
        image, mask = image_and_mask
        assert area(image, mask) == 4.0  # 4 True pixels

    def test_single_pixel_mask(self):
        """Metrics should work with a single-pixel mask."""
        image = np.array([[42.0]])
        mask = np.array([[True]])
        assert mean_intensity(image, mask) == 42.0
        assert max_intensity(image, mask) == 42.0
        assert min_intensity(image, mask) == 42.0
        assert integrated_intensity(image, mask) == 42.0
        assert std_intensity(image, mask) == 0.0
        assert area(image, mask) == 1.0

    def test_metrics_return_float(self, image_and_mask):
        """All metrics must return float, not numpy scalar."""
        image, mask = image_and_mask
        for func in [mean_intensity, max_intensity, min_intensity,
                     integrated_intensity, std_intensity, median_intensity, area]:
            result = func(image, mask)
            assert isinstance(result, float), f"{func.__name__} returned {type(result)}"


# --- MetricRegistry tests ---


class TestMetricRegistry:
    def test_default_has_7_builtins(self):
        reg = MetricRegistry()
        assert len(reg) == 7

    def test_list_metrics_sorted(self):
        reg = MetricRegistry()
        names = reg.list_metrics()
        assert names == sorted(names)
        assert "mean_intensity" in names
        assert "area" in names

    def test_contains(self):
        reg = MetricRegistry()
        assert "mean_intensity" in reg
        assert "nonexistent" not in reg

    def test_compute_builtin(self):
        reg = MetricRegistry()
        image = np.array([[10, 20], [30, 40]], dtype=np.float64)
        mask = np.ones((2, 2), dtype=bool)
        result = reg.compute("mean_intensity", image, mask)
        assert result == pytest.approx(25.0)

    def test_compute_unknown_raises(self):
        reg = MetricRegistry()
        image = np.zeros((2, 2))
        mask = np.ones((2, 2), dtype=bool)
        with pytest.raises(KeyError, match="Unknown metric"):
            reg.compute("bogus", image, mask)

    def test_register_custom_metric(self):
        reg = MetricRegistry()

        def my_metric(image, mask):
            return 42.0

        reg.register("my_metric", my_metric)
        assert "my_metric" in reg
        assert len(reg) == 8

        image = np.zeros((2, 2))
        mask = np.ones((2, 2), dtype=bool)
        assert reg.compute("my_metric", image, mask) == 42.0

    def test_register_overrides_existing(self):
        reg = MetricRegistry()

        def custom_mean(image, mask):
            return -1.0

        reg.register("mean_intensity", custom_mean)
        image = np.ones((2, 2))
        mask = np.ones((2, 2), dtype=bool)
        assert reg.compute("mean_intensity", image, mask) == -1.0

    def test_register_empty_name_raises(self):
        reg = MetricRegistry()
        with pytest.raises(ValueError, match="must not be empty"):
            reg.register("", lambda img, m: 0.0)
