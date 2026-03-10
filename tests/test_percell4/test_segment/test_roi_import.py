"""Tests for percell4.segment.roi_import — label image import."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from percell4.core.constants import FovStatus
from percell4.core.db_types import new_uuid, uuid_to_hex
from percell4.core.experiment_store import ExperimentStore
from percell4.segment.roi_import import import_label_image

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
SAMPLE_TOML = FIXTURES_DIR / "sample_experiment.toml"


@pytest.fixture()
def percell_dir(tmp_path: Path) -> Path:
    """Return a fresh temporary directory to use as .percell root."""
    return tmp_path / "test.percell"


@pytest.fixture()
def store_with_fov(percell_dir: Path):
    """Create an experiment with a single FOV (no image data needed for import).

    Yields (store, fov_id, exp_id, pipeline_run_id).
    """
    store = ExperimentStore.create(percell_dir, SAMPLE_TOML)

    exp = store.get_experiment()
    exp_id = exp["id"]

    fov_id = new_uuid()
    fov_hex = uuid_to_hex(fov_id)

    # Write minimal image so FOV has a valid zarr path
    zarr_path = store.layers.write_image_channels(
        fov_hex, {0: np.zeros((64, 64), dtype=np.uint16)}
    )

    with store.transaction():
        store.insert_fov(
            id=fov_id,
            experiment_id=exp_id,
            status="pending",
            auto_name="FOV_001",
            zarr_path=zarr_path,
        )
        store.set_fov_status(fov_id, FovStatus.imported, "test setup")

    # Create a pipeline run for the import
    run_id = new_uuid()
    with store.transaction():
        store.db.insert_pipeline_run(run_id, "label_import_test")

    yield store, fov_id, exp_id, run_id
    store.close()


class TestImportLabelImage:
    """Tests for import_label_image()."""

    def test_import_label_image(self, store_with_fov) -> None:
        """Import a synthetic label image and verify ROIs created."""
        store, fov_id, exp_id, run_id = store_with_fov

        # Create a synthetic label image with 3 regions
        labels = np.zeros((64, 64), dtype=np.int32)
        labels[5:20, 5:20] = 1    # 15x15 = 225 px
        labels[25:45, 25:45] = 2  # 20x20 = 400 px
        labels[50:60, 50:60] = 3  # 10x10 = 100 px

        count = import_label_image(
            store=store,
            fov_id=fov_id,
            label_image=labels,
            roi_type_name="cell",
            pipeline_run_id=run_id,
        )

        assert count == 3

        # Verify ROIs in DB
        roi_types = store.db.get_roi_type_definitions(exp_id)
        cell_type = next(rt for rt in roi_types if rt["name"] == "cell")
        rois = store.db.get_rois_by_fov_and_type(fov_id, cell_type["id"])
        assert len(rois) == 3

        # Each ROI has a cell_identity_id
        for roi in rois:
            assert roi["cell_identity_id"] is not None
            ci = store.db.get_cell_identity(roi["cell_identity_id"])
            assert ci is not None
            assert ci["origin_fov_id"] == fov_id
            assert ci["roi_type_id"] == cell_type["id"]

        # Verify assignment
        active = store.get_active_assignments(fov_id)
        assert len(active["segmentation"]) == 1
        assert active["segmentation"][0]["assigned_by"] == "label_image_import"

    def test_import_with_correct_roi_type(self, store_with_fov) -> None:
        """Imported ROIs have the correct roi_type_id."""
        store, fov_id, exp_id, run_id = store_with_fov

        labels = np.zeros((64, 64), dtype=np.int32)
        labels[10:30, 10:30] = 1

        count = import_label_image(
            store=store,
            fov_id=fov_id,
            label_image=labels,
            roi_type_name="cell",
            pipeline_run_id=run_id,
        )

        assert count == 1

        roi_types = store.db.get_roi_type_definitions(exp_id)
        cell_type = next(rt for rt in roi_types if rt["name"] == "cell")
        rois = store.db.get_rois_by_fov_and_type(fov_id, cell_type["id"])
        assert len(rois) == 1
        assert rois[0]["roi_type_id"] == cell_type["id"]

    def test_import_non_integer_raises(self, store_with_fov) -> None:
        """Float label image raises ValueError."""
        store, fov_id, _, run_id = store_with_fov

        labels = np.zeros((64, 64), dtype=np.float32)
        with pytest.raises(ValueError, match="integer dtype"):
            import_label_image(
                store=store,
                fov_id=fov_id,
                label_image=labels,
                roi_type_name="cell",
                pipeline_run_id=run_id,
            )

    def test_import_non_2d_raises(self, store_with_fov) -> None:
        """3D label image raises ValueError."""
        store, fov_id, _, run_id = store_with_fov

        labels = np.zeros((64, 64, 3), dtype=np.int32)
        with pytest.raises(ValueError, match="2D"):
            import_label_image(
                store=store,
                fov_id=fov_id,
                label_image=labels,
                roi_type_name="cell",
                pipeline_run_id=run_id,
            )

    def test_import_bad_roi_type_raises(self, store_with_fov) -> None:
        """Non-existent ROI type raises ValueError."""
        store, fov_id, _, run_id = store_with_fov

        labels = np.zeros((64, 64), dtype=np.int32)
        labels[10:20, 10:20] = 1

        with pytest.raises(ValueError, match="not found"):
            import_label_image(
                store=store,
                fov_id=fov_id,
                label_image=labels,
                roi_type_name="nonexistent_type",
                pipeline_run_id=run_id,
            )

    def test_import_empty_labels(self, store_with_fov) -> None:
        """Importing all-zero labels creates 0 ROIs."""
        store, fov_id, _, run_id = store_with_fov

        labels = np.zeros((64, 64), dtype=np.int32)
        count = import_label_image(
            store=store,
            fov_id=fov_id,
            label_image=labels,
            roi_type_name="cell",
            pipeline_run_id=run_id,
        )

        assert count == 0
