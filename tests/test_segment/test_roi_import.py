"""Tests for RoiImporter — pre-existing label import."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from percell3.core import ExperimentStore
from percell3.segment.roi_import import RoiImporter


@pytest.fixture
def experiment_with_region(tmp_path: Path) -> ExperimentStore:
    """Create an experiment with 1 region and DAPI channel."""
    store = ExperimentStore.create(tmp_path / "test.percell")
    store.add_channel("DAPI", role="segmentation")
    store.add_channel("manual")
    store.add_condition("control")

    image = np.random.randint(0, 65535, (128, 128), dtype=np.uint16)
    store.add_region("region_1", "control", width=128, height=128, pixel_size_um=0.65)
    store.write_image("region_1", "control", "DAPI", image)

    yield store
    store.close()


class TestImportLabels:
    """Tests for RoiImporter.import_labels()."""

    def test_import_two_cell_label_image(
        self, experiment_with_region: ExperimentStore
    ) -> None:
        """Import 2-cell label image: cells in DB match."""
        store = experiment_with_region
        importer = RoiImporter()

        labels = np.zeros((128, 128), dtype=np.int32)
        labels[10:40, 10:40] = 1  # Cell 1
        labels[60:90, 60:90] = 2  # Cell 2

        run_id = importer.import_labels(
            labels, store, "region_1", "control", channel="manual"
        )

        assert run_id >= 1
        cell_count = store.get_cell_count()
        assert cell_count == 2

    def test_labels_round_trip(
        self, experiment_with_region: ExperimentStore
    ) -> None:
        """Stored labels should match input."""
        store = experiment_with_region
        importer = RoiImporter()

        labels = np.zeros((128, 128), dtype=np.int32)
        labels[10:40, 10:40] = 1
        labels[50:80, 50:80] = 2

        importer.import_labels(labels, store, "region_1", "control", channel="manual")

        stored = store.read_labels("region_1", "control")
        np.testing.assert_array_equal(stored, labels)

    def test_non_integer_dtype_raises(
        self, experiment_with_region: ExperimentStore
    ) -> None:
        """Float labels should raise ValueError."""
        store = experiment_with_region
        importer = RoiImporter()

        labels = np.zeros((128, 128), dtype=np.float32)
        labels[10:20, 10:20] = 1.0

        with pytest.raises(ValueError, match="integer dtype"):
            importer.import_labels(labels, store, "region_1", "control")

    def test_3d_labels_raises(
        self, experiment_with_region: ExperimentStore
    ) -> None:
        """3D labels should raise ValueError."""
        store = experiment_with_region
        importer = RoiImporter()

        labels = np.zeros((10, 128, 128), dtype=np.int32)

        with pytest.raises(ValueError, match="2D"):
            importer.import_labels(labels, store, "region_1", "control")

    def test_zero_cell_label_image(
        self, experiment_with_region: ExperimentStore
    ) -> None:
        """All-zero labels: run created, 0 cells."""
        store = experiment_with_region
        importer = RoiImporter()

        labels = np.zeros((128, 128), dtype=np.int32)

        run_id = importer.import_labels(
            labels, store, "region_1", "control", channel="manual"
        )

        assert run_id >= 1
        cell_count = store.get_cell_count()
        assert cell_count == 0

    def test_segmentation_run_recorded(
        self, experiment_with_region: ExperimentStore
    ) -> None:
        """Import should create a segmentation run with source metadata."""
        store = experiment_with_region
        importer = RoiImporter()

        labels = np.zeros((128, 128), dtype=np.int32)
        labels[10:30, 10:30] = 1

        run_id = importer.import_labels(
            labels, store, "region_1", "control",
            channel="manual", source="imagej",
        )

        runs = store.get_segmentation_runs()
        run = [r for r in runs if r["id"] == run_id][0]
        assert run["model_name"] == "imagej"

    def test_cell_count_updated_in_run(
        self, experiment_with_region: ExperimentStore
    ) -> None:
        """Run cell_count should be updated after import."""
        store = experiment_with_region
        importer = RoiImporter()

        labels = np.zeros((128, 128), dtype=np.int32)
        labels[10:40, 10:40] = 1
        labels[60:90, 60:90] = 2

        run_id = importer.import_labels(
            labels, store, "region_1", "control", channel="manual"
        )

        runs = store.get_segmentation_runs()
        run = [r for r in runs if r["id"] == run_id][0]
        assert run["cell_count"] == 2


class TestImportCellposeSeg:
    """Tests for RoiImporter.import_cellpose_seg()."""

    def test_import_seg_npy(
        self, experiment_with_region: ExperimentStore, tmp_path: Path
    ) -> None:
        """Import _seg.npy: masks extracted, cells in DB."""
        store = experiment_with_region
        importer = RoiImporter()

        # Create synthetic _seg.npy
        masks = np.zeros((128, 128), dtype=np.int32)
        masks[20:50, 20:50] = 1
        masks[70:100, 70:100] = 2

        seg_data = {
            "masks": masks,
            "est_diam": 30.0,
            "model_path": "/path/to/model",
        }

        seg_path = tmp_path / "test_seg.npy"
        np.save(str(seg_path), seg_data, allow_pickle=True)

        run_id = importer.import_cellpose_seg(
            seg_path, store, "region_1", "control", channel="manual"
        )

        assert run_id >= 1
        cell_count = store.get_cell_count()
        assert cell_count == 2

    def test_seg_npy_parameters_captured(
        self, experiment_with_region: ExperimentStore, tmp_path: Path
    ) -> None:
        """Parameters from _seg.npy should be stored in segmentation run."""
        store = experiment_with_region
        importer = RoiImporter()

        masks = np.zeros((128, 128), dtype=np.int32)
        masks[10:30, 10:30] = 1

        seg_data = {"masks": masks, "est_diam": 45.0}
        seg_path = tmp_path / "test_seg.npy"
        np.save(str(seg_path), seg_data, allow_pickle=True)

        run_id = importer.import_cellpose_seg(
            seg_path, store, "region_1", "control", channel="manual"
        )

        runs = store.get_segmentation_runs()
        run = [r for r in runs if r["id"] == run_id][0]
        assert run["model_name"] == "cellpose-gui"
        assert run["parameters"]["diameter"] == 45.0

    def test_seg_npy_missing_masks_key_raises(
        self, experiment_with_region: ExperimentStore, tmp_path: Path
    ) -> None:
        """_seg.npy without "masks" key should raise ValueError."""
        store = experiment_with_region
        importer = RoiImporter()

        seg_data = {"flows": np.zeros((10, 10)), "styles": np.zeros(256)}
        seg_path = tmp_path / "bad_seg.npy"
        np.save(str(seg_path), seg_data, allow_pickle=True)

        with pytest.raises(ValueError, match="missing 'masks' key"):
            importer.import_cellpose_seg(
                seg_path, store, "region_1", "control"
            )

    def test_seg_npy_file_not_found(
        self, experiment_with_region: ExperimentStore, tmp_path: Path
    ) -> None:
        """Non-existent _seg.npy should raise FileNotFoundError."""
        store = experiment_with_region
        importer = RoiImporter()

        with pytest.raises(FileNotFoundError):
            importer.import_cellpose_seg(
                tmp_path / "nonexistent_seg.npy",
                store, "region_1", "control",
            )
