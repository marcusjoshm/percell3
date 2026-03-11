"""Tests for ThresholdBGSubtractionPlugin — single derived FOV with NaN outside ROIs.

Uses synthetic images with known background values to verify exact subtraction.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from percell4.core.constants import FovStatus
from percell4.core.db_types import new_uuid, uuid_to_hex
from percell4.core.experiment_store import ExperimentStore
from percell4.plugins.threshold_bg_subtraction import ThresholdBGSubtractionPlugin
from percell4.plugins.threshold_bg_subtraction_core import (
    CellBGInfo,
    build_derived_image,
    estimate_group_background,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
SAMPLE_TOML = FIXTURES_DIR / "sample_experiment.toml"


def _setup_fov_with_cells(store, n_cells=2, bg_value=50, signal_value=200):
    """Create a FOV with known cells, segmentation, label image, and intensity groups.

    Layout (128x128 image):
      - Cell 1 (label=1): bbox [10:40, 10:40], actual mask is 15x15 at [15:30, 15:30]
      - Cell 2 (label=2): bbox [60:90, 60:90], actual mask is 15x15 at [65:80, 65:80]
      - Background everywhere else is bg_value
      - Cell pixels are signal_value
      - Dilute phase (inside bbox, outside mask) is bg_value
    """
    exp = store.db.get_experiment()
    exp_id = exp["id"]
    channels = store.db.get_channels(exp_id)
    channel_id = channels[0]["id"]  # DAPI
    roi_types = store.db.get_roi_type_definitions(exp_id)
    cell_type = [rt for rt in roi_types if rt["name"] == "cell"][0]

    # Create image: background is bg_value, cell regions are signal_value
    image = np.full((128, 128), bg_value, dtype=np.uint16)
    image[15:30, 15:30] = signal_value  # cell 1
    image[65:80, 65:80] = signal_value  # cell 2

    # Create label image matching the cells
    label_image = np.zeros((128, 128), dtype=np.int32)
    label_image[15:30, 15:30] = 1  # cell 1
    label_image[65:80, 65:80] = 2  # cell 2

    # Channel 1 (GFP) stays uniform
    ch1_image = np.full((128, 128), 100, dtype=np.uint16)

    # Write FOV image data
    fov_id = new_uuid()
    fov_hex = uuid_to_hex(fov_id)
    zarr_path = store.layers.write_image_channels(
        fov_hex, {0: image, 1: ch1_image}
    )

    # Create pipeline run
    run_id = new_uuid()
    with store.db.transaction():
        store.db.insert_pipeline_run(run_id, "test_setup")

    # Create segmentation set
    seg_set_id = new_uuid()
    seg_set_hex = uuid_to_hex(seg_set_id)

    with store.db.transaction():
        store.db.insert_fov(
            id=fov_id, experiment_id=exp_id,
            status="pending", auto_name="TEST_FOV",
            zarr_path=zarr_path,
        )
        store.db.set_fov_status(fov_id, FovStatus.imported, "test")

        store.db.insert_segmentation_set(
            id=seg_set_id, experiment_id=exp_id,
            produces_roi_type_id=cell_type["id"],
            seg_type="manual",
        )

    # Write label image
    store.layers.write_labels(seg_set_hex, fov_hex, label_image)

    # Assign segmentation to FOV
    with store.db.transaction():
        store.db.assign_segmentation(
            [fov_id], seg_set_id, cell_type["id"],
            run_id, assigned_by="test",
        )

    # Create cell identities and ROIs
    cell_ids = []
    roi_ids = []
    cell_identity_ids = []
    cells_info = [
        {"label_id": 1, "bbox_y": 10, "bbox_x": 10, "bbox_h": 30, "bbox_w": 30, "area_px": 225},
        {"label_id": 2, "bbox_y": 60, "bbox_x": 60, "bbox_h": 30, "bbox_w": 30, "area_px": 225},
    ]

    with store.db.transaction():
        for ci in cells_info[:n_cells]:
            cell_identity_id = new_uuid()
            store.db.insert_cell_identity(
                cell_identity_id, fov_id, cell_type["id"]
            )
            cell_identity_ids.append(cell_identity_id)

            roi_id = new_uuid()
            store.db.insert_roi(
                id=roi_id,
                fov_id=fov_id,
                roi_type_id=cell_type["id"],
                cell_identity_id=cell_identity_id,
                parent_roi_id=None,
                label_id=ci["label_id"],
                bbox_y=ci["bbox_y"],
                bbox_x=ci["bbox_x"],
                bbox_h=ci["bbox_h"],
                bbox_w=ci["bbox_w"],
                area_px=ci["area_px"],
            )
            roi_ids.append(roi_id)

    # Create intensity groups and assign cells
    group_id = new_uuid()
    with store.db.transaction():
        store.db.insert_intensity_group(
            id=group_id,
            experiment_id=exp_id,
            name="DAPI_g1",
            channel_id=channel_id,
            pipeline_run_id=run_id,
            group_index=0,
            lower_bound=0.0,
            upper_bound=500.0,
        )
        for roi_id in roi_ids:
            store.db.insert_cell_group_assignment(
                id=new_uuid(),
                intensity_group_id=group_id,
                roi_id=roi_id,
                pipeline_run_id=run_id,
            )

    return {
        "exp_id": exp_id,
        "fov_id": fov_id,
        "fov_hex": fov_hex,
        "roi_ids": roi_ids,
        "cell_identity_ids": cell_identity_ids,
        "group_id": group_id,
        "run_id": run_id,
        "bg_value": bg_value,
        "signal_value": signal_value,
        "label_image": label_image,
        "image": image,
    }


@pytest.fixture()
def bgsub_store(tmp_path: Path):
    """Create experiment with FOV, cells, segmentation, and intensity groups."""
    percell_dir = tmp_path / "bgsub.percell"
    store = ExperimentStore.create(percell_dir, SAMPLE_TOML)
    info = _setup_fov_with_cells(store, n_cells=2, bg_value=50, signal_value=200)
    yield store, info
    store.close()


# ---------------------------------------------------------------------------
# Core math tests
# ---------------------------------------------------------------------------


class TestEstimateGroupBackground:
    """Tests for estimate_group_background core function."""

    def test_uniform_background(self):
        """With uniform bg outside cells, estimate should match bg value."""
        image = np.full((64, 64), 50, dtype=np.uint16)
        image[10:20, 10:20] = 200  # cell signal

        label_image = np.zeros((64, 64), dtype=np.int32)
        label_image[10:20, 10:20] = 1

        bg = estimate_group_background(
            image, label_image,
            cell_label_ids=[1],
            cell_bboxes=[(5, 5, 25, 25)],
        )

        assert abs(bg - 50.0) < 10.0, f"Expected bg ~50, got {bg}"

    def test_no_dilute_pixels(self):
        """If bbox exactly covers cell mask, returns 0."""
        image = np.full((64, 64), 100, dtype=np.uint16)
        label_image = np.ones((64, 64), dtype=np.int32)  # entire image is cell

        bg = estimate_group_background(
            image, label_image,
            cell_label_ids=[1],
            cell_bboxes=[(0, 0, 64, 64)],
        )

        assert bg == 0.0


class TestBuildDerivedImage:
    """Tests for build_derived_image core function."""

    def test_nan_outside_rois(self):
        """Pixels outside all ROIs should be NaN."""
        image = np.full((64, 64), 100.0, dtype=np.float32)
        label_image = np.zeros((64, 64), dtype=np.int32)
        label_image[10:20, 10:20] = 1

        infos = [
            CellBGInfo(
                label_id=1, group_name="g1", bg_value=30.0,
                bbox=(5, 5, 25, 25),
            )
        ]
        result = build_derived_image(image, label_image, infos)

        # Inside cell: should be 100 - 30 = 70
        assert result[15, 15] == pytest.approx(70.0)
        # Outside cell: should be NaN
        assert np.isnan(result[0, 0])
        assert np.isnan(result[50, 50])

    def test_subtraction_clipped_at_zero(self):
        """Values should not go below zero after subtraction."""
        image = np.full((32, 32), 20.0, dtype=np.float32)
        label_image = np.zeros((32, 32), dtype=np.int32)
        label_image[5:15, 5:15] = 1

        infos = [
            CellBGInfo(
                label_id=1, group_name="g1", bg_value=50.0,
                bbox=(0, 0, 20, 20),
            )
        ]
        result = build_derived_image(image, label_image, infos)

        # 20 - 50 = -30, clipped to 0
        assert result[10, 10] == pytest.approx(0.0)

    def test_dtype_is_float32(self):
        """Output should always be float32."""
        image = np.full((32, 32), 100, dtype=np.uint16)
        label_image = np.zeros((32, 32), dtype=np.int32)
        label_image[5:15, 5:15] = 1

        infos = [
            CellBGInfo(
                label_id=1, group_name="g1", bg_value=10.0,
                bbox=(0, 0, 20, 20),
            )
        ]
        result = build_derived_image(image, label_image, infos)
        assert result.dtype == np.float32

    def test_multiple_cells_different_bg(self):
        """Each cell gets its own group's background subtracted."""
        image = np.full((64, 64), 100.0, dtype=np.float32)
        label_image = np.zeros((64, 64), dtype=np.int32)
        label_image[5:15, 5:15] = 1
        label_image[30:40, 30:40] = 2

        infos = [
            CellBGInfo(
                label_id=1, group_name="g1", bg_value=20.0,
                bbox=(0, 0, 20, 20),
            ),
            CellBGInfo(
                label_id=2, group_name="g2", bg_value=40.0,
                bbox=(25, 25, 20, 20),
            ),
        ]
        result = build_derived_image(image, label_image, infos)

        # Cell 1: 100 - 20 = 80
        assert result[10, 10] == pytest.approx(80.0)
        # Cell 2: 100 - 40 = 60
        assert result[35, 35] == pytest.approx(60.0)
        # Between cells: NaN
        assert np.isnan(result[20, 20])


# ---------------------------------------------------------------------------
# Integration tests (plugin with ExperimentStore)
# ---------------------------------------------------------------------------


def test_creates_single_derived_fov(bgsub_store) -> None:
    """Plugin creates exactly one derived FOV per source FOV."""
    store, info = bgsub_store

    plugin = ThresholdBGSubtractionPlugin()
    result = plugin.run(
        store,
        fov_ids=[info["fov_id"]],
        channel="DAPI",
    )

    assert result.derived_fovs_created == 1
    assert result.fovs_processed == 1
    assert len(result.errors) == 0


def test_derived_fov_has_nan_outside_rois(bgsub_store) -> None:
    """Derived FOV target channel has NaN outside ROI regions."""
    store, info = bgsub_store

    plugin = ThresholdBGSubtractionPlugin()
    plugin.run(store, fov_ids=[info["fov_id"]], channel="DAPI")

    # Find derived FOV
    all_fovs = store.db.get_fovs(info["exp_id"])
    derived = [f for f in all_fovs if f["parent_fov_id"] == info["fov_id"]]
    assert len(derived) == 1

    derived_hex = uuid_to_hex(derived[0]["id"])
    ch0 = store.layers.read_image_channel_numpy(derived_hex, 0)

    # Outside any cell region should be NaN
    assert np.isnan(ch0[0, 0]), "Pixel outside ROIs should be NaN"
    assert np.isnan(ch0[50, 50]), "Pixel between cells should be NaN"


def test_derived_fov_pixel_values(bgsub_store) -> None:
    """Cell pixels are reduced by the estimated background value."""
    store, info = bgsub_store

    plugin = ThresholdBGSubtractionPlugin()
    plugin.run(store, fov_ids=[info["fov_id"]], channel="DAPI")

    all_fovs = store.db.get_fovs(info["exp_id"])
    derived = [f for f in all_fovs if f["parent_fov_id"] == info["fov_id"]]
    derived_hex = uuid_to_hex(derived[0]["id"])
    ch0 = store.layers.read_image_channel_numpy(derived_hex, 0)

    # Cell 1 is at [15:30, 15:30] with signal=200, bg~50
    # After subtraction: ~150 (exact depends on histogram estimation)
    cell1_val = ch0[20, 20]
    assert not np.isnan(cell1_val), "Cell pixel should not be NaN"
    assert cell1_val < 200, "Cell pixel should be reduced by bg subtraction"
    assert cell1_val > 100, f"Cell pixel should be signal-bg, got {cell1_val}"


def test_non_target_channel_preserved_as_float32(bgsub_store) -> None:
    """Non-target channels are preserved (converted to float32)."""
    store, info = bgsub_store

    plugin = ThresholdBGSubtractionPlugin()
    plugin.run(store, fov_ids=[info["fov_id"]], channel="DAPI")

    all_fovs = store.db.get_fovs(info["exp_id"])
    derived = [f for f in all_fovs if f["parent_fov_id"] == info["fov_id"]]
    derived_hex = uuid_to_hex(derived[0]["id"])

    ch1 = store.layers.read_image_channel_numpy(derived_hex, 1)
    # GFP channel should be preserved at 100
    assert ch1[0, 0] == pytest.approx(100.0)


def test_derivation_op_is_set(bgsub_store) -> None:
    """Derived FOV has derivation_op='threshold_bg_subtraction'."""
    store, info = bgsub_store

    plugin = ThresholdBGSubtractionPlugin()
    plugin.run(store, fov_ids=[info["fov_id"]], channel="DAPI")

    all_fovs = store.db.get_fovs(info["exp_id"])
    derived = [f for f in all_fovs if f["parent_fov_id"] == info["fov_id"]]
    assert derived[0]["derivation_op"] == "threshold_bg_subtraction"


def test_cell_identity_preserved(bgsub_store) -> None:
    """Derived FOV ROIs preserve original cell_identity_id references."""
    store, info = bgsub_store

    plugin = ThresholdBGSubtractionPlugin()
    plugin.run(store, fov_ids=[info["fov_id"]], channel="DAPI")

    all_fovs = store.db.get_fovs(info["exp_id"])
    derived = [f for f in all_fovs if f["parent_fov_id"] == info["fov_id"]]
    derived_fov_id = derived[0]["id"]

    # Get cells from derived FOV
    derived_cells = store.db.get_cells(derived_fov_id)
    derived_ci_ids = sorted([c["cell_identity_id"] for c in derived_cells])
    original_ci_ids = sorted(info["cell_identity_ids"])

    assert derived_ci_ids == original_ci_ids


def test_no_groups_raises_error(tmp_path: Path) -> None:
    """Plugin raises RuntimeError when no intensity groups exist."""
    percell_dir = tmp_path / "no_groups.percell"
    store = ExperimentStore.create(percell_dir, SAMPLE_TOML)

    exp = store.db.get_experiment()
    fov_id = new_uuid()
    fov_hex = uuid_to_hex(fov_id)
    img = np.zeros((32, 32), dtype=np.uint16)
    zarr_path = store.layers.write_image_channels(fov_hex, {0: img})
    with store.db.transaction():
        store.db.insert_fov(
            id=fov_id, experiment_id=exp["id"],
            status="pending", auto_name="TEST",
            zarr_path=zarr_path,
        )
        store.db.set_fov_status(fov_id, FovStatus.imported, "test")

    plugin = ThresholdBGSubtractionPlugin()
    with pytest.raises(RuntimeError, match="No intensity groups"):
        plugin.run(store, fov_ids=[fov_id], channel="DAPI")

    store.close()


def test_no_channel_raises_error(bgsub_store) -> None:
    """Plugin raises RuntimeError when channel parameter missing."""
    store, info = bgsub_store

    plugin = ThresholdBGSubtractionPlugin()
    with pytest.raises(RuntimeError, match="channel"):
        plugin.run(store, fov_ids=[info["fov_id"]])


def test_fov_without_cells_reports_error(bgsub_store) -> None:
    """FOVs without cells are skipped with an error message."""
    store, info = bgsub_store

    # Create an empty FOV (no cells)
    exp_id = info["exp_id"]
    empty_fov_id = new_uuid()
    empty_hex = uuid_to_hex(empty_fov_id)
    img = np.zeros((32, 32), dtype=np.uint16)
    zarr_path = store.layers.write_image_channels(empty_hex, {0: img, 1: img})
    with store.db.transaction():
        store.db.insert_fov(
            id=empty_fov_id, experiment_id=exp_id,
            status="pending", auto_name="EMPTY_FOV",
            zarr_path=zarr_path,
        )
        store.db.set_fov_status(empty_fov_id, FovStatus.imported, "test")

    plugin = ThresholdBGSubtractionPlugin()
    result = plugin.run(
        store, fov_ids=[empty_fov_id], channel="DAPI"
    )

    assert result.derived_fovs_created == 0
    assert any("no cells" in e for e in result.errors)


def test_derived_fov_dtype_is_float32(bgsub_store) -> None:
    """Derived FOV channels should be float32 for NaN support."""
    store, info = bgsub_store

    plugin = ThresholdBGSubtractionPlugin()
    plugin.run(store, fov_ids=[info["fov_id"]], channel="DAPI")

    all_fovs = store.db.get_fovs(info["exp_id"])
    derived = [f for f in all_fovs if f["parent_fov_id"] == info["fov_id"]]
    derived_hex = uuid_to_hex(derived[0]["id"])

    ch0 = store.layers.read_image_channel_numpy(derived_hex, 0)
    assert ch0.dtype == np.float32
