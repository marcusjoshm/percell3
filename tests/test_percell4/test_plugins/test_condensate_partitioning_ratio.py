"""Tests for CondensatePartitioningRatioPlugin — ratio calculation."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from percell4.core.constants import FovStatus
from percell4.core.db_types import new_uuid, uuid_to_hex
from percell4.core.experiment_store import ExperimentStore
from percell4.plugins.condensate_partitioning_ratio import (
    CondensatePartitioningRatioPlugin,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
SAMPLE_TOML = FIXTURES_DIR / "sample_experiment.toml"


@pytest.fixture()
def ratio_store(tmp_path: Path):
    """Create experiment with FOV, cell, and particle mask for ratio tests."""
    percell_dir = tmp_path / "ratio.percell"
    store = ExperimentStore.create(percell_dir, SAMPLE_TOML)

    exp = store.db.get_experiment()
    exp_id = exp["id"]
    roi_types = store.db.get_roi_type_definitions(exp_id)
    cell_type = [rt for rt in roi_types if rt["name"] == "cell"][0]

    # Create FOV with known intensity
    fov_id = new_uuid()
    fov_hex = uuid_to_hex(fov_id)
    # Channel 0: bg=50, particle=200 (ratio should be ~200/50 = 4.0)
    ch0 = np.ones((64, 64), dtype=np.uint16) * 50
    ch0[25:35, 25:35] = 200  # particle region
    ch1 = np.ones((64, 64), dtype=np.uint16) * 30
    channel_arrays = {0: ch0, 1: ch1}
    zarr_path = store.layers.write_image_channels(fov_hex, channel_arrays)

    with store.db.transaction():
        store.db.insert_fov(
            id=fov_id, experiment_id=exp_id,
            status="pending", auto_name="FOV_RATIO",
            zarr_path=zarr_path,
        )
        store.db.set_fov_status(fov_id, FovStatus.imported, "test")

    # Segmentation
    run_id = new_uuid()
    seg_set_id = new_uuid()
    with store.db.transaction():
        store.db.insert_pipeline_run(run_id, "test_seg")
        store.db.insert_segmentation_set(
            seg_set_id, exp_id, cell_type["id"], "cellpose",
            fov_count=1, total_roi_count=1,
        )
        store.db.assign_segmentation(
            [fov_id], seg_set_id, cell_type["id"], run_id,
            assigned_by="test",
        )

    # Label image: one cell
    seg_hex = uuid_to_hex(seg_set_id)
    labels = np.ones((64, 64), dtype=np.int32)
    store.layers.write_labels(seg_hex, fov_hex, labels)

    # ROI
    ci = new_uuid()
    roi_id = new_uuid()
    with store.db.transaction():
        store.db.insert_cell_identity(ci, fov_id, cell_type["id"])
        store.db.insert_roi(
            id=roi_id, fov_id=fov_id, roi_type_id=cell_type["id"],
            cell_identity_id=ci, parent_roi_id=None,
            label_id=1, bbox_y=0, bbox_x=0, bbox_h=64, bbox_w=64,
            area_px=4096,
        )

    # Particle mask with one particle at center
    mask_id = new_uuid()
    mask_hex = uuid_to_hex(mask_id)
    particle_mask = np.zeros((64, 64), dtype=np.uint8)
    particle_mask[25:35, 25:35] = 1
    store.layers.write_mask(mask_hex, particle_mask)

    thr_run_id = new_uuid()
    with store.db.transaction():
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


def test_partitioning_ratio_produces_measurements(ratio_store) -> None:
    """Ratio plugin finds particles and computes measurements."""
    store, info = ratio_store

    plugin = CondensatePartitioningRatioPlugin()
    result = plugin.run(
        store,
        fov_ids=[info["fov_id"]],
        measurement_channel="DAPI",
        particle_channel="DAPI",
        export_csv=False,
    )

    assert result.fovs_processed == 1
    assert result.rois_processed >= 1
    assert result.measurements_added >= 1


def test_partitioning_ratio_requires_channels(ratio_store) -> None:
    """Raises without required parameters."""
    store, info = ratio_store

    plugin = CondensatePartitioningRatioPlugin()
    with pytest.raises(RuntimeError, match="measurement_channel"):
        plugin.run(store, fov_ids=[info["fov_id"]])
