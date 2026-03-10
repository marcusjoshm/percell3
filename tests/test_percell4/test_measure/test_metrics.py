"""Tests for percell4.measure.metrics — NaN-safe metric functions."""

from __future__ import annotations

import numpy as np
import pytest

from percell4.measure.metrics import (
    METRIC_FUNCTIONS,
    MetricRegistry,
    area,
    integrated_intensity,
    max_intensity,
    mean_intensity,
    median_intensity,
    min_intensity,
    std_intensity,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_image_and_mask():
    """Create a simple 5x5 image with a 3-pixel mask."""
    image = np.zeros((5, 5), dtype=np.float32)
    image[1, 1] = 10.0
    image[1, 2] = 20.0
    image[1, 3] = 30.0
    mask = np.zeros((5, 5), dtype=bool)
    mask[1, 1] = True
    mask[1, 2] = True
    mask[1, 3] = True
    return image, mask


# ===================================================================
# 1. Test each metric with normal values
# ===================================================================


class TestNormalValues:
    """Each metric returns the expected value on a simple image."""

    def test_mean_intensity(self) -> None:
        image, mask = _make_image_and_mask()
        result = mean_intensity(image, mask)
        assert result == pytest.approx(20.0)

    def test_max_intensity(self) -> None:
        image, mask = _make_image_and_mask()
        result = max_intensity(image, mask)
        assert result == pytest.approx(30.0)

    def test_min_intensity(self) -> None:
        image, mask = _make_image_and_mask()
        result = min_intensity(image, mask)
        assert result == pytest.approx(10.0)

    def test_integrated_intensity(self) -> None:
        image, mask = _make_image_and_mask()
        result = integrated_intensity(image, mask)
        assert result == pytest.approx(60.0)

    def test_std_intensity(self) -> None:
        image, mask = _make_image_and_mask()
        result = std_intensity(image, mask)
        expected = float(np.std([10.0, 20.0, 30.0]))
        assert result == pytest.approx(expected)

    def test_median_intensity(self) -> None:
        image, mask = _make_image_and_mask()
        result = median_intensity(image, mask)
        assert result == pytest.approx(20.0)

    def test_area(self) -> None:
        image, mask = _make_image_and_mask()
        result = area(image, mask)
        assert result == pytest.approx(3.0)


# ===================================================================
# 2. Test each metric with NaN values
# ===================================================================


class TestNanValues:
    """Metrics handle NaN pixels correctly (NaN-safe functions)."""

    def test_mean_with_nan(self) -> None:
        image = np.array([[np.nan, 10.0, 20.0]], dtype=np.float32)
        mask = np.ones((1, 3), dtype=bool)
        result = mean_intensity(image, mask)
        assert result == pytest.approx(15.0)

    def test_max_with_nan(self) -> None:
        image = np.array([[np.nan, 10.0, 20.0]], dtype=np.float32)
        mask = np.ones((1, 3), dtype=bool)
        result = max_intensity(image, mask)
        assert result == pytest.approx(20.0)

    def test_min_with_nan(self) -> None:
        image = np.array([[np.nan, 10.0, 20.0]], dtype=np.float32)
        mask = np.ones((1, 3), dtype=bool)
        result = min_intensity(image, mask)
        assert result == pytest.approx(10.0)

    def test_integrated_with_nan(self) -> None:
        image = np.array([[np.nan, 10.0, 20.0]], dtype=np.float32)
        mask = np.ones((1, 3), dtype=bool)
        result = integrated_intensity(image, mask)
        assert result == pytest.approx(30.0)

    def test_std_with_nan(self) -> None:
        image = np.array([[np.nan, 10.0, 20.0]], dtype=np.float32)
        mask = np.ones((1, 3), dtype=bool)
        result = std_intensity(image, mask)
        expected = float(np.nanstd([np.nan, 10.0, 20.0]))
        assert result == pytest.approx(expected)

    def test_median_with_nan(self) -> None:
        image = np.array([[np.nan, 10.0, 20.0]], dtype=np.float32)
        mask = np.ones((1, 3), dtype=bool)
        result = median_intensity(image, mask)
        assert result == pytest.approx(15.0)

    def test_area_counts_non_nan(self) -> None:
        """Area should count only non-NaN pixels within the mask."""
        image = np.array([[np.nan, 10.0, 20.0]], dtype=np.float32)
        mask = np.ones((1, 3), dtype=bool)
        result = area(image, mask)
        # Only 2 non-NaN pixels in the mask
        assert result == pytest.approx(2.0)


# ===================================================================
# 3. Test METRIC_FUNCTIONS dict
# ===================================================================


class TestMetricFunctionsDict:
    """METRIC_FUNCTIONS dict contains all 7 built-in metrics."""

    def test_has_all_seven(self) -> None:
        expected = {
            "mean_intensity",
            "max_intensity",
            "min_intensity",
            "integrated_intensity",
            "std_intensity",
            "median_intensity",
            "area",
        }
        assert set(METRIC_FUNCTIONS.keys()) == expected

    def test_all_callable(self) -> None:
        for name, func in METRIC_FUNCTIONS.items():
            assert callable(func), f"{name} is not callable"


# ===================================================================
# 4. Test MetricRegistry
# ===================================================================


class TestMetricRegistry:
    """MetricRegistry provides compute, register, and list operations."""

    def test_default_has_seven(self) -> None:
        registry = MetricRegistry()
        assert len(registry) == 7

    def test_compute_known_metric(self) -> None:
        image, mask = _make_image_and_mask()
        registry = MetricRegistry()
        result = registry.compute("mean_intensity", image, mask)
        assert result == pytest.approx(20.0)

    def test_compute_unknown_raises(self) -> None:
        image, mask = _make_image_and_mask()
        registry = MetricRegistry()
        with pytest.raises(KeyError, match="Unknown metric"):
            registry.compute("nonexistent", image, mask)

    def test_register_custom(self) -> None:
        registry = MetricRegistry()
        registry.register("my_sum", lambda img, m: float(np.sum(img[m])))
        assert "my_sum" in registry
        assert len(registry) == 8

    def test_register_empty_name_raises(self) -> None:
        registry = MetricRegistry()
        with pytest.raises(ValueError, match="empty"):
            registry.register("", lambda img, m: 0.0)

    def test_list_metrics_sorted(self) -> None:
        registry = MetricRegistry()
        names = registry.list_metrics()
        assert names == sorted(names)
        assert len(names) == 7
