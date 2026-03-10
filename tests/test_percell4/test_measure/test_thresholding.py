"""Tests for percell4.measure.thresholding — threshold computation and mask creation."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from percell4.core.db_types import new_uuid, uuid_to_hex
from percell4.core.experiment_store import ExperimentStore
from percell4.measure.thresholding import (
    SUPPORTED_METHODS,
    ThresholdResult,
    compute_threshold,
    create_threshold_mask,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
SAMPLE_TOML = FIXTURES_DIR / "sample_experiment.toml"


# ===================================================================
# 1. compute_threshold tests
# ===================================================================


class TestComputeThreshold:
    """Test the pure compute_threshold function."""

    def test_otsu_bimodal(self) -> None:
        """Otsu threshold on bimodal distribution should be between modes."""
        rng = np.random.default_rng(42)
        low = rng.normal(50, 5, size=500)
        high = rng.normal(200, 5, size=500)
        image = np.concatenate([low, high]).reshape(50, 20).astype(np.float32)

        value = compute_threshold(image, method="otsu")
        # Otsu should be between the two distribution centres
        assert 55.0 < value < 195.0

    def test_manual(self) -> None:
        image = np.zeros((10, 10), dtype=np.float32)
        value = compute_threshold(image, method="manual", manual_value=42.5)
        assert value == pytest.approx(42.5)

    def test_manual_missing_value_raises(self) -> None:
        image = np.zeros((10, 10), dtype=np.float32)
        with pytest.raises(ValueError, match="manual_value"):
            compute_threshold(image, method="manual")

    def test_unknown_method_raises(self) -> None:
        image = np.zeros((10, 10), dtype=np.float32)
        with pytest.raises(ValueError, match="Unknown threshold"):
            compute_threshold(image, method="bogus")


# ===================================================================
# 2. create_threshold_mask integration tests
# ===================================================================


class TestCreateThresholdMask:
    """Integration tests for create_threshold_mask."""

    def test_creates_mask_and_db_record(self, tmp_path: Path) -> None:
        percell_dir = tmp_path / "test.percell"
        store = ExperimentStore.create(percell_dir, SAMPLE_TOML)
        try:
            exp = store.get_experiment()
            experiment_id = exp["id"]

            # Create FOV with a bright/dim image
            fov_id = new_uuid()
            store.db.insert_fov(fov_id, experiment_id, status="imported")

            fov_hex = uuid_to_hex(fov_id)
            # Create a bimodal image: top half bright, bottom half dim
            image = np.zeros((100, 100), dtype=np.float32)
            image[:50, :] = 200.0  # bright
            image[50:, :] = 20.0   # dim
            store.layers.write_image_channels(fov_hex, {0: image, 1: image})

            result = create_threshold_mask(
                store,
                fov_id=fov_id,
                source_channel_name="DAPI",
                method="manual",
                manual_value=100.0,
            )

            assert isinstance(result, ThresholdResult)
            assert isinstance(result.threshold_mask_id, bytes)
            assert len(result.threshold_mask_id) == 16
            assert result.threshold_value == pytest.approx(100.0)

            # Top half (5000 px) is above 100, bottom (5000 px) is below
            assert result.positive_pixels == 5000
            assert result.total_pixels == 10000
            assert result.positive_fraction == pytest.approx(0.5)

            # Verify DB record exists
            masks = store.db.get_threshold_masks(fov_id)
            assert len(masks) == 1
            assert masks[0]["method"] == "manual"
            assert masks[0]["source_channel"] == "DAPI"
            assert masks[0]["status"] == "computed"

            # Verify mask is readable from zarr
            mask_hex = uuid_to_hex(result.threshold_mask_id)
            stored_mask = store.layers.read_mask(mask_hex)
            assert stored_mask.shape == (100, 100)
            assert np.sum(stored_mask > 0) == 5000
        finally:
            store.close()

    def test_otsu_method(self, tmp_path: Path) -> None:
        percell_dir = tmp_path / "otsu.percell"
        store = ExperimentStore.create(percell_dir, SAMPLE_TOML)
        try:
            exp = store.get_experiment()
            fov_id = new_uuid()
            store.db.insert_fov(fov_id, exp["id"], status="imported")

            fov_hex = uuid_to_hex(fov_id)
            rng = np.random.default_rng(42)
            image = np.zeros((100, 100), dtype=np.float32)
            image[:50, :] = rng.normal(200, 10, size=(50, 100))
            image[50:, :] = rng.normal(20, 10, size=(50, 100))
            store.layers.write_image_channels(fov_hex, {0: image, 1: image})

            result = create_threshold_mask(
                store,
                fov_id=fov_id,
                source_channel_name="DAPI",
                method="otsu",
            )

            # Otsu should find a threshold between the two modes
            assert 50.0 < result.threshold_value < 180.0
            # Most of the top half should be positive
            assert result.positive_fraction > 0.3
        finally:
            store.close()

    def test_unknown_channel_raises(self, tmp_path: Path) -> None:
        percell_dir = tmp_path / "bad_ch.percell"
        store = ExperimentStore.create(percell_dir, SAMPLE_TOML)
        try:
            exp = store.get_experiment()
            fov_id = new_uuid()
            store.db.insert_fov(fov_id, exp["id"], status="imported")

            with pytest.raises(ValueError, match="not found"):
                create_threshold_mask(
                    store,
                    fov_id=fov_id,
                    source_channel_name="NONEXISTENT",
                )
        finally:
            store.close()
