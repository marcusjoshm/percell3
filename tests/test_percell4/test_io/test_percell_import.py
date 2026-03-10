"""Tests for percell4.io.percell_import — cross-project FOV import."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from percell4.core.constants import FovStatus
from percell4.core.db_types import new_uuid, uuid_to_hex
from percell4.core.experiment_store import ExperimentStore
from percell4.io.percell_import import import_fov_from_experiment

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
SAMPLE_TOML = FIXTURES_DIR / "sample_experiment.toml"


def _create_store(base_path: Path, name: str) -> ExperimentStore:
    """Create a fresh ExperimentStore at base_path/name."""
    return ExperimentStore.create(base_path / name, SAMPLE_TOML)


def _add_fov_with_image(
    store: ExperimentStore,
    fov_name: str = "test_fov",
) -> bytes:
    """Add an FOV with a single-channel image and return the FOV ID."""
    exp = store.get_experiment()
    fov_id = new_uuid()
    fov_hex = uuid_to_hex(fov_id)

    # Write a test image
    arr = np.random.randint(0, 1000, (32, 32), dtype=np.uint16)
    zarr_path = store.layers.write_image_channels(fov_hex, {0: arr})

    # Insert FOV record
    with store.transaction():
        store.db.insert_fov(
            id=fov_id,
            experiment_id=exp["id"],
            auto_name=fov_name,
            zarr_path=zarr_path,
            status="pending",
        )
        store.db.set_fov_status(fov_id, FovStatus.imported, "test")

    return fov_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestImportFovCreatesNewUuids:
    """Importing an FOV creates new UUIDs in the target."""

    def test_new_fov_id(self, tmp_path: Path) -> None:
        """The target FOV has a different ID than the source."""
        source = _create_store(tmp_path, "source.percell")
        target = _create_store(tmp_path, "target.percell")

        try:
            src_fov_id = _add_fov_with_image(source, "original")

            new_fov_id = import_fov_from_experiment(
                target, source, src_fov_id,
            )

            assert new_fov_id != src_fov_id
            assert isinstance(new_fov_id, bytes)
            assert len(new_fov_id) == 16
        finally:
            source.close()
            target.close()

    def test_target_fov_exists_in_db(self, tmp_path: Path) -> None:
        """The imported FOV is queryable from the target DB."""
        source = _create_store(tmp_path, "source.percell")
        target = _create_store(tmp_path, "target.percell")

        try:
            src_fov_id = _add_fov_with_image(source, "fov_a")

            new_fov_id = import_fov_from_experiment(
                target, source, src_fov_id,
            )

            fov = target.get_fov(new_fov_id)
            assert fov is not None
            assert fov["auto_name"] == "fov_a_imported"
            assert fov["status"] == FovStatus.imported
        finally:
            source.close()
            target.close()

    def test_image_data_copied(self, tmp_path: Path) -> None:
        """Pixel data is copied to the target LayerStore."""
        source = _create_store(tmp_path, "source.percell")
        target = _create_store(tmp_path, "target.percell")

        try:
            exp = source.get_experiment()
            src_fov_id = new_uuid()
            src_fov_hex = uuid_to_hex(src_fov_id)

            # Write known test data
            test_arr = np.arange(64, dtype=np.uint16).reshape(8, 8)
            zarr_path = source.layers.write_image_channels(
                src_fov_hex, {0: test_arr}
            )

            with source.transaction():
                source.db.insert_fov(
                    id=src_fov_id,
                    experiment_id=exp["id"],
                    auto_name="data_fov",
                    zarr_path=zarr_path,
                    status="pending",
                )
                source.db.set_fov_status(
                    src_fov_id, FovStatus.imported, "test"
                )

            new_fov_id = import_fov_from_experiment(
                target, source, src_fov_id,
            )

            new_hex = uuid_to_hex(new_fov_id)
            read_back = target.layers.read_image_channel_numpy(new_hex, 0)
            np.testing.assert_array_equal(read_back, test_arr)
        finally:
            source.close()
            target.close()

    def test_same_project_raises(self, tmp_path: Path) -> None:
        """Importing from the same project directory raises ValueError."""
        store = _create_store(tmp_path, "same.percell")

        try:
            src_fov_id = _add_fov_with_image(store, "fov")

            with pytest.raises(ValueError, match="same experiment"):
                import_fov_from_experiment(store, store, src_fov_id)
        finally:
            store.close()

    def test_missing_fov_raises(self, tmp_path: Path) -> None:
        """Importing a non-existent FOV ID raises KeyError."""
        source = _create_store(tmp_path, "source.percell")
        target = _create_store(tmp_path, "target.percell")

        try:
            fake_id = new_uuid()
            with pytest.raises(KeyError):
                import_fov_from_experiment(target, source, fake_id)
        finally:
            source.close()
            target.close()
