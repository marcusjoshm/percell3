"""Tests for NanZeroPlugin — the canary test for the plugin system.

Creates a real experiment with ExperimentStore.create(), imports a test FOV
with known image data containing zeros, runs NanZeroPlugin, and verifies:
- Derived FOV created
- Zero pixels replaced with NaN
- Non-zero pixels unchanged
- ROIs duplicated
- Assignments copied
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from percell4.core.constants import FovStatus
from percell4.core.db_types import new_uuid, uuid_to_hex
from percell4.core.experiment_store import ExperimentStore
from percell4.plugins.nan_zero import NanZeroPlugin

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
SAMPLE_TOML = FIXTURES_DIR / "sample_experiment.toml"


@pytest.fixture()
def populated_store(tmp_path: Path):
    """Create an ExperimentStore with one FOV containing known pixel data."""
    percell_dir = tmp_path / "test.percell"
    store = ExperimentStore.create(percell_dir, SAMPLE_TOML)

    exp = store.get_experiment()
    exp_id = exp["id"]
    channels = store.get_channels(exp_id)
    roi_types = store.db.get_roi_type_definitions(exp_id)
    type_map = {rt["name"]: rt for rt in roi_types}
    cell_type = type_map["cell"]

    # Create a condition
    cond_id = new_uuid()
    with store.transaction():
        store.db.insert_condition(cond_id, exp_id, "control")

    # Create FOV with test data:
    # Channel 0 (DAPI): mix of 0s and 100s
    # Channel 1 (GFP): all 200s (no zeros)
    fov_id = new_uuid()
    fov_hex = uuid_to_hex(fov_id)

    ch0_data = np.ones((64, 64), dtype=np.uint16) * 100
    ch0_data[0:10, 0:10] = 0  # Zero region
    ch1_data = np.ones((64, 64), dtype=np.uint16) * 200

    channel_arrays = {0: ch0_data, 1: ch1_data}
    zarr_path = store.layers.write_image_channels(fov_hex, channel_arrays)

    with store.transaction():
        store.insert_fov(
            id=fov_id,
            experiment_id=exp_id,
            condition_id=cond_id,
            status="pending",
            auto_name="FOV_001",
            zarr_path=zarr_path,
        )
        store.set_fov_status(fov_id, FovStatus.imported, "test setup")

    # Create pipeline run
    run_id = new_uuid()
    with store.transaction():
        store.db.insert_pipeline_run(run_id, "test_segmentation")

    # Create segmentation set
    seg_set_id = new_uuid()
    with store.transaction():
        store.db.insert_segmentation_set(
            seg_set_id, exp_id, cell_type["id"], "cellpose",
            fov_count=1, total_roi_count=2,
        )

    # Assign segmentation to FOV
    with store.transaction():
        store.db.assign_segmentation(
            [fov_id], seg_set_id, cell_type["id"], run_id,
            assigned_by="test",
        )

    # Create cell identities and ROIs
    ci_1 = new_uuid()
    ci_2 = new_uuid()
    roi_1 = new_uuid()
    roi_2 = new_uuid()
    with store.transaction():
        store.db.insert_cell_identity(ci_1, fov_id, cell_type["id"])
        store.db.insert_cell_identity(ci_2, fov_id, cell_type["id"])
        store.db.insert_roi(
            id=roi_1, fov_id=fov_id, roi_type_id=cell_type["id"],
            cell_identity_id=ci_1, parent_roi_id=None,
            label_id=1, bbox_y=0, bbox_x=0, bbox_h=32, bbox_w=32,
            area_px=500,
        )
        store.db.insert_roi(
            id=roi_2, fov_id=fov_id, roi_type_id=cell_type["id"],
            cell_identity_id=ci_2, parent_roi_id=None,
            label_id=2, bbox_y=32, bbox_x=32, bbox_h=32, bbox_w=32,
            area_px=300,
        )

    info = {
        "exp_id": exp_id,
        "fov_id": fov_id,
        "channels": channels,
        "cell_type": cell_type,
        "seg_set_id": seg_set_id,
        "run_id": run_id,
        "roi_1": roi_1,
        "roi_2": roi_2,
        "ci_1": ci_1,
        "ci_2": ci_2,
    }

    yield store, info
    store.close()


def test_nan_zero_creates_derived_fov(populated_store) -> None:
    """NanZeroPlugin creates a derived FOV."""
    store, info = populated_store

    plugin = NanZeroPlugin()
    result = plugin.run(
        store,
        fov_ids=[info["fov_id"]],
        channels=["DAPI"],
    )

    assert result.derived_fovs_created == 1
    assert result.fovs_processed == 1
    assert not result.errors


def test_nan_zero_replaces_zeros_with_nan(populated_store) -> None:
    """Zero pixels in the target channel become NaN."""
    store, info = populated_store

    plugin = NanZeroPlugin()
    plugin.run(
        store,
        fov_ids=[info["fov_id"]],
        channels=["DAPI"],
    )

    # Find the derived FOV
    exp_id = info["exp_id"]
    all_fovs = store.get_fovs(exp_id)
    derived_fovs = [f for f in all_fovs if f["parent_fov_id"] == info["fov_id"]]
    assert len(derived_fovs) == 1

    derived_fov = derived_fovs[0]
    derived_hex = uuid_to_hex(derived_fov["id"])

    # Read channel 0 (DAPI) from derived FOV
    ch0 = store.layers.read_image_channel_numpy(derived_hex, 0)

    # The 10x10 zero region should now be NaN
    assert np.all(np.isnan(ch0[0:10, 0:10])), "Zero pixels should be NaN"

    # Non-zero pixels should be unchanged (100.0 as float32)
    assert ch0[30, 30] == pytest.approx(100.0)


def test_nan_zero_preserves_non_target_channels(populated_store) -> None:
    """Non-target channels are copied unchanged (still float32)."""
    store, info = populated_store

    plugin = NanZeroPlugin()
    plugin.run(
        store,
        fov_ids=[info["fov_id"]],
        channels=["DAPI"],
    )

    exp_id = info["exp_id"]
    all_fovs = store.get_fovs(exp_id)
    derived_fovs = [f for f in all_fovs if f["parent_fov_id"] == info["fov_id"]]
    derived_hex = uuid_to_hex(derived_fovs[0]["id"])

    # Channel 1 (GFP) should be unchanged
    ch1 = store.layers.read_image_channel_numpy(derived_hex, 1)
    assert ch1[0, 0] == pytest.approx(200.0)
    assert not np.any(np.isnan(ch1))


def test_nan_zero_duplicates_rois(populated_store) -> None:
    """ROIs from source FOV are duplicated to derived FOV."""
    store, info = populated_store

    plugin = NanZeroPlugin()
    plugin.run(
        store,
        fov_ids=[info["fov_id"]],
        channels=["DAPI"],
    )

    exp_id = info["exp_id"]
    all_fovs = store.get_fovs(exp_id)
    derived_fovs = [f for f in all_fovs if f["parent_fov_id"] == info["fov_id"]]
    derived_id = derived_fovs[0]["id"]

    # Get ROIs from derived FOV
    derived_cells = store.db.get_cells(derived_id)
    assert len(derived_cells) == 2

    # Should have new IDs but same cell identities
    derived_roi_ids = {c["id"] for c in derived_cells}
    assert info["roi_1"] not in derived_roi_ids
    assert info["roi_2"] not in derived_roi_ids

    derived_identities = {c["cell_identity_id"] for c in derived_cells}
    assert info["ci_1"] in derived_identities
    assert info["ci_2"] in derived_identities


def test_nan_zero_copies_assignments(populated_store) -> None:
    """Active assignments are copied from source to derived FOV."""
    store, info = populated_store

    plugin = NanZeroPlugin()
    plugin.run(
        store,
        fov_ids=[info["fov_id"]],
        channels=["DAPI"],
    )

    exp_id = info["exp_id"]
    all_fovs = store.get_fovs(exp_id)
    derived_fovs = [f for f in all_fovs if f["parent_fov_id"] == info["fov_id"]]
    derived_id = derived_fovs[0]["id"]

    active = store.get_active_assignments(derived_id)
    assert len(active["segmentation"]) >= 1
    seg = active["segmentation"][0]
    assert seg["segmentation_set_id"] == info["seg_set_id"]


def test_nan_zero_requires_channels_param() -> None:
    """Raises when channels parameter is missing."""
    plugin = NanZeroPlugin()
    with pytest.raises(RuntimeError, match="channels"):
        plugin.run(None, fov_ids=[b"\x00" * 16])  # type: ignore[arg-type]


def test_nan_zero_derived_fov_status(populated_store) -> None:
    """Derived FOV status is 'imported'."""
    store, info = populated_store

    plugin = NanZeroPlugin()
    plugin.run(
        store,
        fov_ids=[info["fov_id"]],
        channels=["DAPI"],
    )

    exp_id = info["exp_id"]
    all_fovs = store.get_fovs(exp_id)
    derived_fovs = [f for f in all_fovs if f["parent_fov_id"] == info["fov_id"]]
    derived_id = derived_fovs[0]["id"]

    status = store.get_fov_status(derived_id)
    assert status == "imported"
