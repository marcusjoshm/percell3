"""Tests for percell4.measure.measurer — core measurement functions."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from percell4.core.constants import SCOPE_MASK_INSIDE, SCOPE_MASK_OUTSIDE, SCOPE_WHOLE_ROI
from percell4.core.db_types import new_uuid, uuid_to_hex
from percell4.core.experiment_store import ExperimentStore
from percell4.measure.measurer import Measurer, measure_roi
from percell4.measure.metrics import METRIC_FUNCTIONS

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
SAMPLE_TOML = FIXTURES_DIR / "sample_experiment.toml"


def _create_store_with_fov(tmp_path: Path):
    """Create a store with one FOV, one segmentation, and two ROIs.

    Returns (store, fov_id, seg_set_id, roi_type_id, channel_ids, pipeline_run_id).
    """
    percell_dir = tmp_path / "test.percell"
    store = ExperimentStore.create(percell_dir, SAMPLE_TOML)

    exp = store.get_experiment()
    experiment_id = exp["id"]
    channels = store.get_channels(experiment_id)
    channel_ids = [ch["id"] for ch in channels]

    # Get cell ROI type
    roi_types = store.db.get_roi_type_definitions(experiment_id)
    cell_type_id = None
    for rt in roi_types:
        if rt["name"] == "cell":
            cell_type_id = rt["id"]
            break

    # Create pipeline run
    pipeline_run_id = new_uuid()
    store.db.insert_pipeline_run(pipeline_run_id, "test_measurement")

    # Create FOV
    fov_id = new_uuid()
    store.db.insert_fov(fov_id, experiment_id, status="imported")

    # Write a synthetic 50x50 image (2 channels)
    fov_hex = uuid_to_hex(fov_id)
    image0 = np.full((50, 50), 100.0, dtype=np.float32)
    image1 = np.full((50, 50), 200.0, dtype=np.float32)
    # Make a bright region for ROI 1 (label=1) at top-left
    image0[5:15, 5:15] = 500.0
    image1[5:15, 5:15] = 1000.0
    # ROI 2 (label=2) at bottom-right
    image0[30:40, 30:40] = 300.0
    image1[30:40, 30:40] = 600.0

    store.layers.write_image_channels(fov_hex, {0: image0, 1: image1})

    # Create segmentation set
    seg_set_id = new_uuid()
    store.db.insert_segmentation_set(
        seg_set_id, experiment_id, cell_type_id, "cellpose",
    )

    # Write label image
    labels = np.zeros((50, 50), dtype=np.int32)
    labels[5:15, 5:15] = 1
    labels[30:40, 30:40] = 2
    seg_hex = uuid_to_hex(seg_set_id)
    store.layers.write_labels(seg_hex, fov_hex, labels)

    # Assign segmentation
    store.db.assign_segmentation(
        [fov_id], seg_set_id, cell_type_id, pipeline_run_id,
    )

    # Create cell identities and ROIs
    ci1 = new_uuid()
    store.db.insert_cell_identity(ci1, fov_id, cell_type_id)
    roi1_id = new_uuid()
    store.db.insert_roi(
        roi1_id, fov_id, cell_type_id, ci1, None,
        label_id=1, bbox_y=5, bbox_x=5, bbox_h=10, bbox_w=10, area_px=100,
    )

    ci2 = new_uuid()
    store.db.insert_cell_identity(ci2, fov_id, cell_type_id)
    roi2_id = new_uuid()
    store.db.insert_roi(
        roi2_id, fov_id, cell_type_id, ci2, None,
        label_id=2, bbox_y=30, bbox_x=30, bbox_h=10, bbox_w=10, area_px=100,
    )

    return store, fov_id, seg_set_id, cell_type_id, channel_ids, pipeline_run_id


# ===================================================================
# 1. test_measure_roi with synthetic image and mask
# ===================================================================


class TestMeasureRoi:
    """Test the standalone measure_roi function."""

    def test_basic_measurement(self) -> None:
        image = np.zeros((20, 20), dtype=np.float32)
        image[5:10, 5:10] = 50.0
        mask = np.zeros((20, 20), dtype=bool)
        mask[5:10, 5:10] = True

        result = measure_roi(image, mask, bbox=(5, 5, 5, 5))
        assert result["mean_intensity"] == pytest.approx(50.0)
        assert result["max_intensity"] == pytest.approx(50.0)
        assert result["min_intensity"] == pytest.approx(50.0)
        assert result["integrated_intensity"] == pytest.approx(50.0 * 25)
        assert result["area"] == pytest.approx(25.0)

    def test_empty_mask_returns_zeros(self) -> None:
        image = np.ones((10, 10), dtype=np.float32)
        mask = np.zeros((10, 10), dtype=bool)
        result = measure_roi(image, mask, bbox=(0, 0, 10, 10))
        for name, val in result.items():
            assert val == 0.0, f"{name} should be 0.0 for empty mask"

    def test_all_seven_metrics_present(self) -> None:
        image = np.ones((10, 10), dtype=np.float32)
        mask = np.ones((10, 10), dtype=bool)
        result = measure_roi(image, mask, bbox=(0, 0, 10, 10))
        assert set(result.keys()) == set(METRIC_FUNCTIONS.keys())


# ===================================================================
# 2. Integration: measure_fov_whole
# ===================================================================


class TestMeasureFovWhole:
    """Integration test: create experiment, write images, insert ROIs, measure."""

    def test_measures_all_rois(self, tmp_path: Path) -> None:
        store, fov_id, seg_set_id, cell_type_id, channel_ids, pr_id = (
            _create_store_with_fov(tmp_path)
        )
        try:
            measurer = Measurer()
            count = measurer.measure_fov_whole(
                store,
                fov_id=fov_id,
                channel_id=channel_ids[0],  # DAPI
                seg_set_id=seg_set_id,
                roi_type_id=cell_type_id,
                pipeline_run_id=pr_id,
            )
            # 2 ROIs x 7 metrics = 14
            assert count == 14

            # Verify measurements are in DB
            measurements = store.db.get_active_measurements(fov_id)
            whole_roi_meas = [
                m for m in measurements if m["scope"] == SCOPE_WHOLE_ROI
            ]
            assert len(whole_roi_meas) == 14
        finally:
            store.close()

    def test_correct_values(self, tmp_path: Path) -> None:
        """Verify actual metric values for the first ROI."""
        store, fov_id, seg_set_id, cell_type_id, channel_ids, pr_id = (
            _create_store_with_fov(tmp_path)
        )
        try:
            measurer = Measurer()
            measurer.measure_fov_whole(
                store,
                fov_id=fov_id,
                channel_id=channel_ids[0],
                seg_set_id=seg_set_id,
                roi_type_id=cell_type_id,
                pipeline_run_id=pr_id,
            )

            measurements = store.db.get_active_measurements(fov_id)
            # Get ROI1's measurements
            rois = store.db.get_rois_by_fov_and_type(fov_id, cell_type_id)
            roi1 = [r for r in rois if r["label_id"] == 1][0]

            roi1_mean = [
                m for m in measurements
                if m["roi_id"] == roi1["id"]
                and m["metric"] == "mean_intensity"
            ]
            assert len(roi1_mean) == 1
            # ROI 1 region is all 500.0
            assert roi1_mean[0]["value"] == pytest.approx(500.0)
        finally:
            store.close()

    def test_no_rois_returns_zero(self, tmp_path: Path) -> None:
        """If no ROIs exist, returns 0."""
        percell_dir = tmp_path / "empty.percell"
        store = ExperimentStore.create(percell_dir, SAMPLE_TOML)
        try:
            exp = store.get_experiment()
            fov_id = new_uuid()
            store.db.insert_fov(fov_id, exp["id"], status="imported")
            channels = store.get_channels(exp["id"])
            roi_types = store.db.get_roi_type_definitions(exp["id"])
            cell_type_id = [rt for rt in roi_types if rt["name"] == "cell"][0]["id"]

            seg_set_id = new_uuid()
            store.db.insert_segmentation_set(
                seg_set_id, exp["id"], cell_type_id, "cellpose",
            )

            measurer = Measurer()
            count = measurer.measure_fov_whole(
                store,
                fov_id=fov_id,
                channel_id=channels[0]["id"],
                seg_set_id=seg_set_id,
                roi_type_id=cell_type_id,
                pipeline_run_id=new_uuid(),
            )
            assert count == 0
        finally:
            store.close()


# ===================================================================
# 3. Integration: measure_fov_masked
# ===================================================================


class TestMeasureFovMasked:
    """Integration test for masked measurements."""

    def test_masked_measurements(self, tmp_path: Path) -> None:
        store, fov_id, seg_set_id, cell_type_id, channel_ids, pr_id = (
            _create_store_with_fov(tmp_path)
        )
        try:
            # Create a threshold mask: left half is True
            mask = np.zeros((50, 50), dtype=np.uint8)
            mask[:, :25] = 1
            mask_id = new_uuid()
            mask_hex = uuid_to_hex(mask_id)
            store.layers.write_mask(mask_hex, mask)

            store.db.insert_threshold_mask(
                id=mask_id,
                fov_id=fov_id,
                source_channel="DAPI",
                method="manual",
                threshold_value=0.5,
                zarr_path=f"zarr/masks/{mask_hex}",
                status="computed",
            )

            measurer = Measurer()
            count = measurer.measure_fov_masked(
                store,
                fov_id=fov_id,
                channel_id=channel_ids[0],
                seg_set_id=seg_set_id,
                roi_type_id=cell_type_id,
                mask_id=mask_id,
                scopes=[SCOPE_MASK_INSIDE, SCOPE_MASK_OUTSIDE],
                pipeline_run_id=pr_id,
            )

            # ROI1 (5:15, 5:15): all inside mask (x<25)
            # ROI2 (30:40, 30:40): all outside mask (x>=25)
            # 2 ROIs x 2 scopes x 7 metrics = 28
            assert count == 28
        finally:
            store.close()

    def test_invalid_scope_raises(self, tmp_path: Path) -> None:
        store, fov_id, seg_set_id, cell_type_id, channel_ids, pr_id = (
            _create_store_with_fov(tmp_path)
        )
        try:
            measurer = Measurer()
            with pytest.raises(ValueError, match="Invalid scope"):
                measurer.measure_fov_masked(
                    store,
                    fov_id=fov_id,
                    channel_id=channel_ids[0],
                    seg_set_id=seg_set_id,
                    roi_type_id=cell_type_id,
                    mask_id=new_uuid(),
                    scopes=["bad_scope"],
                    pipeline_run_id=pr_id,
                )
        finally:
            store.close()
