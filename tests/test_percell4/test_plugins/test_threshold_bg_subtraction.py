"""Tests for ThresholdBGSubtractionPlugin — creates derived FOV with BG subtracted."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from percell4.core.constants import FovStatus
from percell4.core.db_types import new_uuid, uuid_to_hex
from percell4.core.experiment_store import ExperimentStore
from percell4.plugins.threshold_bg_subtraction import ThresholdBGSubtractionPlugin

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
SAMPLE_TOML = FIXTURES_DIR / "sample_experiment.toml"


@pytest.fixture()
def bgsub_store(tmp_path: Path):
    """Create experiment with histogram FOV + apply FOV + mask."""
    percell_dir = tmp_path / "bgsub.percell"
    store = ExperimentStore.create(percell_dir, SAMPLE_TOML)

    exp = store.get_experiment()
    exp_id = exp["id"]
    roi_types = store.db.get_roi_type_definitions(exp_id)
    cell_type = [rt for rt in roi_types if rt["name"] == "cell"][0]

    # Create histogram FOV with bimodal data: bg ~50, signal ~200
    hist_fov_id = new_uuid()
    hist_hex = uuid_to_hex(hist_fov_id)
    hist_ch0 = np.ones((64, 64), dtype=np.uint16) * 50
    hist_ch0[20:40, 20:40] = 200  # signal region
    hist_ch1 = np.ones((64, 64), dtype=np.uint16) * 30
    hist_arrays = {0: hist_ch0, 1: hist_ch1}
    hist_zarr = store.layers.write_image_channels(hist_hex, hist_arrays)

    with store.transaction():
        store.insert_fov(
            id=hist_fov_id, experiment_id=exp_id,
            status="pending", auto_name="HIST_FOV",
            zarr_path=hist_zarr,
        )
        store.set_fov_status(hist_fov_id, FovStatus.imported, "test")

    # Create apply FOV with uniform data
    apply_fov_id = new_uuid()
    apply_hex = uuid_to_hex(apply_fov_id)
    apply_ch0 = np.ones((64, 64), dtype=np.uint16) * 150
    apply_ch1 = np.ones((64, 64), dtype=np.uint16) * 80
    apply_arrays = {0: apply_ch0, 1: apply_ch1}
    apply_zarr = store.layers.write_image_channels(apply_hex, apply_arrays)

    with store.transaction():
        store.insert_fov(
            id=apply_fov_id, experiment_id=exp_id,
            status="pending", auto_name="APPLY_FOV",
            zarr_path=apply_zarr,
        )
        store.set_fov_status(apply_fov_id, FovStatus.imported, "test")

    # Create mask on histogram FOV (whole image is masked)
    run_id = new_uuid()
    with store.transaction():
        store.db.insert_pipeline_run(run_id, "test_threshold")

    mask_id = new_uuid()
    mask_hex = uuid_to_hex(mask_id)
    mask_data = np.ones((64, 64), dtype=np.uint8)
    store.layers.write_mask(mask_hex, mask_data)

    with store.transaction():
        store.db.insert_threshold_mask(
            id=mask_id, fov_id=hist_fov_id,
            source_channel="DAPI", method="manual",
            threshold_value=25.0,
            zarr_path=f"zarr/masks/{mask_hex}",
        )
        store.db.assign_mask(
            [hist_fov_id], mask_id, "measurement_scope",
            run_id, assigned_by="test",
        )

    info = {
        "exp_id": exp_id,
        "hist_fov_id": hist_fov_id,
        "apply_fov_id": apply_fov_id,
        "mask_id": mask_id,
    }

    yield store, info
    store.close()


def test_threshold_bg_subtraction_creates_derived(bgsub_store) -> None:
    """BG subtraction creates a derived FOV from apply FOV."""
    store, info = bgsub_store

    plugin = ThresholdBGSubtractionPlugin()
    result = plugin.run(
        store,
        fov_ids=[info["apply_fov_id"]],
        channel="DAPI",
        pairings=[{
            "histogram_fov_id": info["hist_fov_id"],
            "apply_fov_id": info["apply_fov_id"],
        }],
    )

    assert result.derived_fovs_created == 1
    assert result.fovs_processed == 1


def test_threshold_bg_subtraction_pixel_values(bgsub_store) -> None:
    """Derived FOV channel values are reduced by background estimate."""
    store, info = bgsub_store

    plugin = ThresholdBGSubtractionPlugin()
    plugin.run(
        store,
        fov_ids=[info["apply_fov_id"]],
        channel="DAPI",
        pairings=[{
            "histogram_fov_id": info["hist_fov_id"],
            "apply_fov_id": info["apply_fov_id"],
        }],
    )

    # Find derived FOV
    all_fovs = store.get_fovs(info["exp_id"])
    derived = [f for f in all_fovs if f["parent_fov_id"] == info["apply_fov_id"]]
    assert len(derived) == 1

    derived_hex = uuid_to_hex(derived[0]["id"])
    ch0 = store.layers.read_image_channel_numpy(derived_hex, 0)

    # Original was 150, BG estimate should be somewhere around 50
    # After subtraction, values should be less than 150
    assert ch0[0, 0] < 150

    # Non-target channel should be preserved
    ch1 = store.layers.read_image_channel_numpy(derived_hex, 1)
    assert ch1[0, 0] == 80
