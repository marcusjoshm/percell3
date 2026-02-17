"""Tests for ThresholdEngine — thresholding methods and mask storage."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from percell3.core import ExperimentStore
from percell3.measure.thresholding import SUPPORTED_METHODS, ThresholdEngine, ThresholdResult


@pytest.fixture
def threshold_experiment(tmp_path: Path) -> ExperimentStore:
    """Experiment with a bimodal GFP image suitable for thresholding."""
    store = ExperimentStore.create(tmp_path / "thresh.percell")
    store.add_channel("GFP")
    store.add_condition("control")
    store.add_region("region_1", "control", width=64, height=64)

    # Bimodal image: background ~20, foreground ~200
    rng = np.random.default_rng(42)
    image = np.zeros((64, 64), dtype=np.uint16)
    image[:, :] = (rng.normal(20, 3, (64, 64)).clip(0, 65535)).astype(np.uint16)
    image[20:50, 20:50] = (rng.normal(200, 10, (30, 30)).clip(0, 65535)).astype(np.uint16)
    store.write_image("region_1", "control", "GFP", image)

    yield store
    store.close()


class TestThresholdEngine:

    def test_otsu_threshold(self, threshold_experiment: ExperimentStore):
        """Otsu should find a threshold between background and foreground."""
        engine = ThresholdEngine()
        result = engine.threshold_region(
            threshold_experiment, region="region_1", condition="control",
            channel="GFP", method="otsu",
        )
        assert isinstance(result, ThresholdResult)
        assert result.threshold_run_id >= 1
        # Threshold should be between background (~20) and foreground (~200)
        assert 20 < result.threshold_value < 200
        assert result.positive_pixels > 0
        assert result.total_pixels == 64 * 64
        assert 0.0 < result.positive_fraction < 1.0

    def test_manual_threshold(self, threshold_experiment: ExperimentStore):
        """Manual threshold should use the exact value provided."""
        engine = ThresholdEngine()
        result = engine.threshold_region(
            threshold_experiment, region="region_1", condition="control",
            channel="GFP", method="manual", manual_value=100.0,
        )
        assert result.threshold_value == 100.0
        # Foreground (~200) is above 100, background (~20) below
        assert result.positive_pixels > 0

    def test_manual_without_value_raises(self, threshold_experiment: ExperimentStore):
        """Manual method without manual_value should raise ValueError."""
        engine = ThresholdEngine()
        with pytest.raises(ValueError, match="manual_value is required"):
            engine.threshold_region(
                threshold_experiment, region="region_1", condition="control",
                channel="GFP", method="manual",
            )

    def test_unknown_method_raises(self, threshold_experiment: ExperimentStore):
        """Unknown threshold method should raise ValueError."""
        engine = ThresholdEngine()
        with pytest.raises(ValueError, match="Unknown threshold method"):
            engine.threshold_region(
                threshold_experiment, region="region_1", condition="control",
                channel="GFP", method="bogus",
            )

    def test_triangle_threshold(self, threshold_experiment: ExperimentStore):
        """Triangle method should produce a valid threshold."""
        engine = ThresholdEngine()
        result = engine.threshold_region(
            threshold_experiment, region="region_1", condition="control",
            channel="GFP", method="triangle",
        )
        assert result.threshold_value > 0
        assert result.positive_pixels > 0

    def test_li_threshold(self, threshold_experiment: ExperimentStore):
        """Li method should produce a valid threshold."""
        engine = ThresholdEngine()
        result = engine.threshold_region(
            threshold_experiment, region="region_1", condition="control",
            channel="GFP", method="li",
        )
        assert result.threshold_value > 0
        assert result.positive_pixels > 0

    def test_adaptive_threshold(self, threshold_experiment: ExperimentStore):
        """Adaptive method should produce a mask."""
        engine = ThresholdEngine()
        result = engine.threshold_region(
            threshold_experiment, region="region_1", condition="control",
            channel="GFP", method="adaptive",
        )
        assert result.positive_pixels > 0
        assert result.total_pixels == 64 * 64

    def test_mask_stored_in_zarr(self, threshold_experiment: ExperimentStore):
        """Binary mask should be readable from masks.zarr after thresholding."""
        engine = ThresholdEngine()
        engine.threshold_region(
            threshold_experiment, region="region_1", condition="control",
            channel="GFP", method="otsu",
        )
        mask = threshold_experiment.read_mask("region_1", "control", "GFP")
        assert mask.shape == (64, 64)
        assert mask.dtype == np.uint8
        # Mask values may be 0/1 or 0/255 depending on zarr write/read roundtrip
        assert mask.min() == 0
        assert mask.max() > 0

    def test_threshold_run_recorded(self, threshold_experiment: ExperimentStore):
        """Threshold run should be recorded in the database."""
        engine = ThresholdEngine()
        result = engine.threshold_region(
            threshold_experiment, region="region_1", condition="control",
            channel="GFP", method="otsu",
        )
        assert result.threshold_run_id >= 1

    def test_supported_methods_constant(self):
        """SUPPORTED_METHODS should contain all 5 methods."""
        assert SUPPORTED_METHODS == {"otsu", "adaptive", "manual", "triangle", "li"}

    def test_positive_fraction_calculation(self, threshold_experiment: ExperimentStore):
        """positive_fraction should equal positive_pixels / total_pixels."""
        engine = ThresholdEngine()
        result = engine.threshold_region(
            threshold_experiment, region="region_1", condition="control",
            channel="GFP", method="manual", manual_value=100.0,
        )
        expected = result.positive_pixels / result.total_pixels
        assert result.positive_fraction == pytest.approx(expected)
