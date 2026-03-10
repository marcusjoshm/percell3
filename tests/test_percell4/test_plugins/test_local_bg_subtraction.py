"""Tests for LocalBGSubtractionPlugin — measurement-only operation."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from percell4.core.constants import FovStatus
from percell4.core.db_types import new_uuid, uuid_to_hex
from percell4.core.experiment_store import ExperimentStore
from percell4.plugins.local_bg_subtraction import LocalBGSubtractionPlugin

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
SAMPLE_TOML = FIXTURES_DIR / "sample_experiment.toml"


@pytest.fixture()
def localbg_store(tmp_path: Path):
    """Create experiment with FOV, segmentation, ROIs, and particle mask."""
    percell_dir = tmp_path / "localbg.percell"
    store = ExperimentStore.create(percell_dir, SAMPLE_TOML)

    exp = store.get_experiment()
    exp_id = exp["id"]
    roi_types = store.db.get_roi_type_definitions(exp_id)
    cell_type = [rt for rt in roi_types if rt["name"] == "cell"][0]

    # Create FOV with signal data
    fov_id = new_uuid()
    fov_hex = uuid_to_hex(fov_id)
    # Channel 0: measurement channel with bright particle region
    ch0 = np.ones((64, 64), dtype=np.uint16) * 50  # background
    ch0[15:20, 15:20] = 200  # bright particle
    ch1 = np.ones((64, 64), dtype=np.uint16) * 30
    channel_arrays = {0: ch0, 1: ch1}
    zarr_path = store.layers.write_image_channels(fov_hex, channel_arrays)

    with store.transaction():
        store.insert_fov(
            id=fov_id, experiment_id=exp_id,
            status="pending", auto_name="FOV_LBG",
            zarr_path=zarr_path,
        )
        store.set_fov_status(fov_id, FovStatus.imported, "test")

    # Create pipeline run
    run_id = new_uuid()
    with store.transaction():
        store.db.insert_pipeline_run(run_id, "test_seg")

    # Create segmentation set and assign
    seg_set_id = new_uuid()
    with store.transaction():
        store.db.insert_segmentation_set(
            seg_set_id, exp_id, cell_type["id"], "cellpose",
            fov_count=1, total_roi_count=1,
        )
        store.db.assign_segmentation(
            [fov_id], seg_set_id, cell_type["id"], run_id,
            assigned_by="test",
        )

    # Write label image (one cell covering whole image)
    seg_hex = uuid_to_hex(seg_set_id)
    labels = np.ones((64, 64), dtype=np.int32)
    store.layers.write_labels(seg_hex, fov_hex, labels)

    # Create cell identity and ROI
    ci = new_uuid()
    roi_id = new_uuid()
    with store.transaction():
        store.db.insert_cell_identity(ci, fov_id, cell_type["id"])
        store.db.insert_roi(
            id=roi_id, fov_id=fov_id, roi_type_id=cell_type["id"],
            cell_identity_id=ci, parent_roi_id=None,
            label_id=1, bbox_y=0, bbox_x=0, bbox_h=64, bbox_w=64,
            area_px=4096,
        )

    # Create particle mask (a small bright spot)
    mask_id = new_uuid()
    mask_hex = uuid_to_hex(mask_id)
    particle_mask = np.zeros((64, 64), dtype=np.uint8)
    particle_mask[15:20, 15:20] = 1  # particle label = 1
    store.layers.write_mask(mask_hex, particle_mask)

    thr_run_id = new_uuid()
    with store.transaction():
        store.db.insert_pipeline_run(thr_run_id, "test_threshold")
        store.db.insert_threshold_mask(
            id=mask_id, fov_id=fov_id,
            source_channel="DAPI", method="manual",
            threshold_value=100.0,
            zarr_path=f"zarr/masks/{mask_hex}",
        )
        store.db.assign_mask(
            [fov_id], mask_id, "measurement_scope",
            thr_run_id, assigned_by="test",
        )

    info = {
        "exp_id": exp_id,
        "fov_id": fov_id,
        "roi_id": roi_id,
    }

    yield store, info
    store.close()


def test_local_bg_subtraction_processes_particles(localbg_store) -> None:
    """Local BG subtraction finds and processes particles."""
    store, info = localbg_store

    plugin = LocalBGSubtractionPlugin()
    result = plugin.run(
        store,
        fov_ids=[info["fov_id"]],
        measurement_channel="DAPI",
        particle_channel="DAPI",
        export_csv=False,
    )

    assert result.fovs_processed == 1
    # Should have found at least 1 ROI with particles
    assert result.rois_processed >= 1
    assert result.measurements_added >= 1
    # No derived FOVs — this is measurement-only
    assert result.derived_fovs_created == 0


def test_local_bg_subtraction_requires_channels(localbg_store) -> None:
    """Raises without required channel parameters."""
    store, info = localbg_store

    plugin = LocalBGSubtractionPlugin()
    with pytest.raises(RuntimeError, match="measurement_channel"):
        plugin.run(store, fov_ids=[info["fov_id"]])
