"""Tests for percell4.segment._engine — SegmentationEngine integration test."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from percell4.core.constants import FovStatus
from percell4.core.db_types import new_uuid, uuid_to_hex, uuid_to_str
from percell4.core.experiment_store import ExperimentStore
from percell4.segment._engine import SegmentationEngine
from percell4.segment.cellpose_adapter import MockSegmenter

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
SAMPLE_TOML = FIXTURES_DIR / "sample_experiment.toml"


@pytest.fixture()
def percell_dir(tmp_path: Path) -> Path:
    """Return a fresh temporary directory to use as .percell root."""
    return tmp_path / "test.percell"


@pytest.fixture()
def store_with_fov(percell_dir: Path):
    """Create an experiment with a single FOV containing a synthetic image.

    Yields (store, fov_id, experiment_id).
    """
    store = ExperimentStore.create(percell_dir, SAMPLE_TOML)

    exp = store.db.get_experiment()
    exp_id = exp["id"]

    # Create a synthetic image: two bright squares on dark background
    fov_id = new_uuid()
    fov_hex = uuid_to_hex(fov_id)

    image_dapi = np.zeros((100, 100), dtype=np.uint16)
    image_dapi[20:40, 20:40] = 500   # bright square 1
    image_dapi[60:80, 60:80] = 600   # bright square 2

    image_gfp = np.ones((100, 100), dtype=np.uint16) * 50

    zarr_path = store.layers.write_image_channels(
        fov_hex, {0: image_dapi, 1: image_gfp}
    )

    with store.db.transaction():
        store.db.insert_fov(
            id=fov_id,
            experiment_id=exp_id,
            status="pending",
            auto_name="FOV_001",
            zarr_path=zarr_path,
        )
        store.db.set_fov_status(fov_id, FovStatus.imported, "test setup")

    yield store, fov_id, exp_id
    store.close()


class TestSegmentationPipeline:
    """Full integration test for SegmentationEngine.run()."""

    def test_segmentation_pipeline(self, store_with_fov) -> None:
        """Run full pipeline: segment, verify DB and zarr state."""
        store, fov_id, exp_id = store_with_fov

        engine = SegmentationEngine()
        seg_set_id, measurement_needed = engine.run(
            store=store,
            fov_ids=[fov_id],
            channel_name="DAPI",
            roi_type_name="cell",
            segmenter=MockSegmenter(),
            parameters={"model_name": "mock", "seg_type": "cellular"},
        )

        # --- Verify segmentation_set was created ---
        seg_set = store.db.get_segmentation_set(seg_set_id)
        assert seg_set is not None
        assert seg_set["experiment_id"] == exp_id
        assert seg_set["seg_type"] == "cellular"
        assert seg_set["fov_count"] == 1
        assert seg_set["total_roi_count"] >= 1  # MockSegmenter should find objects

        # --- Verify labels written to zarr ---
        seg_set_hex = uuid_to_hex(seg_set_id)
        fov_hex = uuid_to_hex(fov_id)
        labels = store.layers.read_labels(seg_set_hex, fov_hex)
        assert labels.shape == (100, 100)
        assert labels.max() > 0  # Has labeled regions

        # --- Verify ROIs in DB ---
        roi_types = store.db.get_roi_type_definitions(exp_id)
        cell_type = next(rt for rt in roi_types if rt["name"] == "cell")
        rois = store.db.get_rois_by_fov_and_type(fov_id, cell_type["id"])
        assert len(rois) >= 1

        # Each ROI should have a cell_identity_id
        for roi in rois:
            assert roi["cell_identity_id"] is not None
            assert len(roi["cell_identity_id"]) == 16  # UUID

        # --- Verify cell_identities created ---
        for roi in rois:
            ci = store.db.get_cell_identity(roi["cell_identity_id"])
            assert ci is not None
            assert ci["origin_fov_id"] == fov_id
            assert ci["roi_type_id"] == cell_type["id"]

        # --- Verify assignment created ---
        active = store.db.get_active_assignments(fov_id)
        assert len(active["segmentation"]) == 1
        seg_assign = active["segmentation"][0]
        assert seg_assign["segmentation_set_id"] == seg_set_id
        assert seg_assign["roi_type_id"] == cell_type["id"]
        assert seg_assign["assigned_by"] == "segmentation_engine"

        # --- Verify MeasurementNeeded returned ---
        assert len(measurement_needed) >= 1
        mn = measurement_needed[0]
        assert mn.fov_id == fov_id
        assert mn.roi_type_id == cell_type["id"]
        assert mn.reason == "new_assignment"

    def test_segmentation_with_progress_callback(self, store_with_fov) -> None:
        """Progress callback is invoked correctly."""
        store, fov_id, exp_id = store_with_fov

        progress_calls: list[tuple[int, int]] = []

        def on_progress(current: int, total: int) -> None:
            progress_calls.append((current, total))

        engine = SegmentationEngine()
        engine.run(
            store=store,
            fov_ids=[fov_id],
            channel_name="DAPI",
            roi_type_name="cell",
            segmenter=MockSegmenter(),
            on_progress=on_progress,
        )

        assert len(progress_calls) == 1
        assert progress_calls[0] == (1, 1)

    def test_segmentation_empty_fov_list_raises(self, store_with_fov) -> None:
        """Empty fov_ids raises ValueError."""
        store, _, _ = store_with_fov

        engine = SegmentationEngine()
        with pytest.raises(ValueError, match="must not be empty"):
            engine.run(
                store=store,
                fov_ids=[],
                channel_name="DAPI",
                roi_type_name="cell",
                segmenter=MockSegmenter(),
            )

    def test_segmentation_bad_channel_raises(self, store_with_fov) -> None:
        """Non-existent channel name raises ValueError."""
        store, fov_id, _ = store_with_fov

        engine = SegmentationEngine()
        with pytest.raises(ValueError, match="not found"):
            engine.run(
                store=store,
                fov_ids=[fov_id],
                channel_name="NONEXISTENT",
                roi_type_name="cell",
                segmenter=MockSegmenter(),
            )

    def test_segmentation_bad_roi_type_raises(self, store_with_fov) -> None:
        """Non-existent ROI type name raises ValueError."""
        store, fov_id, _ = store_with_fov

        engine = SegmentationEngine()
        with pytest.raises(ValueError, match="not found"):
            engine.run(
                store=store,
                fov_ids=[fov_id],
                channel_name="DAPI",
                roi_type_name="nonexistent_type",
                segmenter=MockSegmenter(),
            )

    def test_segmentation_multiple_fovs(self, percell_dir: Path) -> None:
        """Segmenting multiple FOVs shares a single segmentation_set."""
        store = ExperimentStore.create(percell_dir, SAMPLE_TOML)
        try:
            exp = store.db.get_experiment()
            exp_id = exp["id"]

            fov_ids = []
            for i in range(3):
                fov_id = new_uuid()
                fov_hex = uuid_to_hex(fov_id)

                image = np.zeros((64, 64), dtype=np.uint16)
                image[10:30, 10:30] = 400 + i * 100
                zarr_path = store.layers.write_image_channels(
                    fov_hex, {0: image, 1: np.zeros((64, 64), dtype=np.uint16)}
                )

                with store.db.transaction():
                    store.db.insert_fov(
                        id=fov_id,
                        experiment_id=exp_id,
                        status="pending",
                        auto_name=f"FOV_{i:03d}",
                        zarr_path=zarr_path,
                    )
                    store.db.set_fov_status(fov_id, FovStatus.imported, "test")
                fov_ids.append(fov_id)

            engine = SegmentationEngine()
            seg_set_id, needed = engine.run(
                store=store,
                fov_ids=fov_ids,
                channel_name="DAPI",
                roi_type_name="cell",
                segmenter=MockSegmenter(),
            )

            # Single segmentation_set with counts for all 3 FOVs
            seg_set = store.db.get_segmentation_set(seg_set_id)
            assert seg_set["fov_count"] == 3

            # Each FOV should have its own assignment
            assert len(needed) == 3

        finally:
            store.close()

    def test_pipeline_run_completed(self, store_with_fov) -> None:
        """Pipeline run status is marked as completed after run."""
        store, fov_id, _ = store_with_fov

        engine = SegmentationEngine()
        seg_set_id, _ = engine.run(
            store=store,
            fov_ids=[fov_id],
            channel_name="DAPI",
            roi_type_name="cell",
            segmenter=MockSegmenter(),
        )

        # Check pipeline_run status
        # Get the assignment to find the pipeline_run_id
        active = store.db.get_active_assignments(fov_id)
        run_id = active["segmentation"][0]["pipeline_run_id"]
        run = store.db.connection.execute(
            "SELECT * FROM pipeline_runs WHERE id = ?", (run_id,)
        ).fetchone()
        assert run["status"] == "completed"
