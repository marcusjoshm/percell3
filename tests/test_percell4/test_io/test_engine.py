"""Tests for percell4.io.engine — ImportEngine."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import tifffile

from percell4.core.constants import FovStatus
from percell4.core.db_types import new_uuid, uuid_to_hex
from percell4.core.experiment_store import ExperimentStore
from percell4.io.engine import ImportEngine

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
SAMPLE_TOML = FIXTURES_DIR / "sample_experiment.toml"


@pytest.fixture()
def percell_dir(tmp_path: Path) -> Path:
    """Return a fresh temporary directory for an experiment."""
    return tmp_path / "test.percell"


@pytest.fixture()
def store(percell_dir: Path) -> ExperimentStore:
    """Create and return a new ExperimentStore (auto-closed)."""
    s = ExperimentStore.create(percell_dir, SAMPLE_TOML)
    yield s
    s.close()


def _write_test_tiff(path: Path, shape: tuple, dtype=np.uint16) -> np.ndarray:
    """Write a test TIFF and return the array."""
    arr = np.random.randint(0, 1000, shape, dtype=dtype)
    tifffile.imwrite(str(path), arr)
    return arr


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestImportSingleTiff:
    """Import a single-channel TIFF file."""

    def test_import_creates_fov_in_db(self, store: ExperimentStore, tmp_path: Path) -> None:
        """A single TIFF import creates one FOV record in the database."""
        arr = _write_test_tiff(tmp_path / "sample.tif", (64, 64))
        exp = store.db.get_experiment()
        channels = store.db.get_channels(exp["id"])
        ch_id = channels[0]["id"]

        engine = ImportEngine()
        fov_ids = engine.import_images(
            store,
            [tmp_path / "sample.tif"],
            channel_mapping={0: ch_id},
        )

        assert len(fov_ids) == 1
        fov = store.db.get_fov(fov_ids[0])
        assert fov is not None
        assert fov["auto_name"] == "sample"

    def test_import_writes_zarr_data(self, store: ExperimentStore, tmp_path: Path) -> None:
        """Imported image data is readable from LayerStore."""
        arr = _write_test_tiff(tmp_path / "pixels.tif", (32, 32))
        exp = store.db.get_experiment()
        channels = store.db.get_channels(exp["id"])
        ch_id = channels[0]["id"]

        engine = ImportEngine()
        fov_ids = engine.import_images(
            store,
            [tmp_path / "pixels.tif"],
            channel_mapping={0: ch_id},
        )

        fov_hex = uuid_to_hex(fov_ids[0])
        read_back = store.layers.read_image_channel_numpy(fov_hex, 0)
        np.testing.assert_array_equal(read_back, arr)

    def test_import_sets_status_imported(self, store: ExperimentStore, tmp_path: Path) -> None:
        """Imported FOV has status 'imported'."""
        _write_test_tiff(tmp_path / "status.tif", (16, 16))
        exp = store.db.get_experiment()
        channels = store.db.get_channels(exp["id"])
        ch_id = channels[0]["id"]

        engine = ImportEngine()
        fov_ids = engine.import_images(
            store,
            [tmp_path / "status.tif"],
            channel_mapping={0: ch_id},
        )

        status = store.db.get_fov_status(fov_ids[0])
        assert status == FovStatus.imported


class TestImportMultiChannel:
    """Import multi-channel TIFFs."""

    def test_multi_channel_import(self, store: ExperimentStore, tmp_path: Path) -> None:
        """A 3D TIFF with multiple channels splits into separate zarr arrays."""
        # 2 channels x 32x32
        arr = np.random.randint(0, 1000, (2, 32, 32), dtype=np.uint16)
        path = tmp_path / "multi.tif"
        tifffile.imwrite(str(path), arr)

        exp = store.db.get_experiment()
        channels = store.db.get_channels(exp["id"])
        ch_mapping = {0: channels[0]["id"], 1: channels[1]["id"]}

        engine = ImportEngine()
        fov_ids = engine.import_images(
            store,
            [path],
            channel_mapping=ch_mapping,
        )

        assert len(fov_ids) == 1
        fov_hex = uuid_to_hex(fov_ids[0])
        ch0 = store.layers.read_image_channel_numpy(fov_hex, 0)
        ch1 = store.layers.read_image_channel_numpy(fov_hex, 1)
        np.testing.assert_array_equal(ch0, arr[0])
        np.testing.assert_array_equal(ch1, arr[1])


class TestImportWithCondition:
    """Import with condition_id assignment."""

    def test_condition_id_assigned(self, store: ExperimentStore, tmp_path: Path) -> None:
        """condition_id is recorded on the FOV record."""
        _write_test_tiff(tmp_path / "cond.tif", (16, 16))
        exp = store.db.get_experiment()
        channels = store.db.get_channels(exp["id"])
        ch_id = channels[0]["id"]

        # Create a condition
        cond_id = new_uuid()
        store.db.connection.execute(
            "INSERT INTO conditions (id, experiment_id, name) VALUES (?, ?, ?)",
            (cond_id, exp["id"], "treated"),
        )
        store.db.connection.commit()

        engine = ImportEngine()
        fov_ids = engine.import_images(
            store,
            [tmp_path / "cond.tif"],
            channel_mapping={0: ch_id},
            condition_id=cond_id,
        )

        fov = store.db.get_fov(fov_ids[0])
        assert fov["condition_id"] == cond_id


class TestProgressCallback:
    """on_progress callback is invoked correctly."""

    def test_callback_called(self, store: ExperimentStore, tmp_path: Path) -> None:
        """Progress callback is called once per source file."""
        _write_test_tiff(tmp_path / "a.tif", (8, 8))
        _write_test_tiff(tmp_path / "b.tif", (8, 8))
        exp = store.db.get_experiment()
        channels = store.db.get_channels(exp["id"])
        ch_id = channels[0]["id"]

        calls: list[tuple[int, int, str]] = []

        engine = ImportEngine()
        engine.import_images(
            store,
            [tmp_path / "a.tif", tmp_path / "b.tif"],
            channel_mapping={0: ch_id},
            on_progress=lambda cur, total, name: calls.append((cur, total, name)),
        )

        assert len(calls) == 2
        assert calls[0] == (0, 2, "a")
        assert calls[1] == (1, 2, "b")
