"""Shared fixtures for percell4 tests.

Provides reusable fixtures for ExperimentDB, ExperimentStore, and common
entity setup helpers to reduce duplication across test modules.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from percell4.core.constants import FovStatus, SCOPE_WHOLE_ROI
from percell4.core.db_types import new_uuid, uuid_to_hex
from percell4.core.experiment_db import ExperimentDB
from percell4.core.experiment_store import ExperimentStore

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
SAMPLE_TOML = FIXTURES_DIR / "sample_experiment.toml"


# ---------------------------------------------------------------------------
# Low-level DB fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    """Return a path to a temporary database file."""
    return tmp_path / "test_experiment.db"


@pytest.fixture()
def db(db_path: Path) -> ExperimentDB:
    """Return an open ExperimentDB instance (auto-closed after test)."""
    database = ExperimentDB(db_path)
    database.open()
    yield database
    database.close()


# ---------------------------------------------------------------------------
# Store-level fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def percell_dir(tmp_path: Path) -> Path:
    """Return a fresh temporary directory to use as .percell root."""
    return tmp_path / "test.percell"


@pytest.fixture()
def created_store(percell_dir: Path) -> ExperimentStore:
    """Create and return a new ExperimentStore (caller must close)."""
    store = ExperimentStore.create(percell_dir, SAMPLE_TOML)
    yield store
    store.close()


# ---------------------------------------------------------------------------
# Populated experiment helpers
# ---------------------------------------------------------------------------


def setup_experiment(db: ExperimentDB) -> bytes:
    """Insert a minimal experiment and return its ID."""
    eid = new_uuid()
    db.insert_experiment(eid, "test_experiment")
    return eid


def setup_condition(db: ExperimentDB, eid: bytes) -> bytes:
    """Insert a minimal condition and return its ID."""
    cid = new_uuid()
    db.insert_condition(cid, eid, "control")
    return cid


def setup_channel(db: ExperimentDB, eid: bytes, name: str = "GFP") -> bytes:
    """Insert a minimal channel and return its ID."""
    chid = new_uuid()
    db.insert_channel(chid, eid, name)
    return chid


def setup_roi_type(
    db: ExperimentDB,
    eid: bytes,
    name: str = "cell",
    parent_type_id: bytes | None = None,
) -> bytes:
    """Insert a minimal ROI type definition and return its ID."""
    rtid = new_uuid()
    db.insert_roi_type_definition(rtid, eid, name, parent_type_id)
    return rtid


def setup_pipeline_run(db: ExperimentDB, op_name: str = "test") -> bytes:
    """Insert a minimal pipeline run and return its ID."""
    run_id = new_uuid()
    db.insert_pipeline_run(run_id, op_name)
    return run_id


def setup_populated_experiment(store: ExperimentStore) -> dict:
    """Create an experiment with FOV, channels, segmentation, ROIs, and measurements.

    Returns a dict with all entity IDs for use in tests.
    """
    exp = store.db.get_experiment()
    exp_id = exp["id"]
    channels = store.db.get_channels(exp_id)
    roi_types = store.db.get_roi_type_definitions(exp_id)

    type_map = {rt["name"]: rt for rt in roi_types}
    cell_type = type_map["cell"]
    particle_type = type_map["particle"]

    # Create a condition
    cond_id = new_uuid()
    with store.db.transaction():
        store.db.insert_condition(cond_id, exp_id, "control")

    # Create source FOV with zarr data
    fov_id = new_uuid()
    fov_hex = uuid_to_hex(fov_id)
    channel_arrays = {
        0: np.ones((64, 64), dtype=np.uint16) * 100,
        1: np.ones((64, 64), dtype=np.uint16) * 200,
    }
    zarr_path = store.layers.write_image_channels(fov_hex, channel_arrays)

    with store.db.transaction():
        store.db.insert_fov(
            id=fov_id,
            experiment_id=exp_id,
            condition_id=cond_id,
            status="pending",
            auto_name="FOV_001",
            zarr_path=zarr_path,
            pixel_size_um=0.11,
        )
        store.db.set_fov_status(fov_id, FovStatus.imported, "test setup")

    # Create pipeline run
    run_id = new_uuid()
    with store.db.transaction():
        store.db.insert_pipeline_run(run_id, "test_segmentation")

    # Create segmentation set
    seg_set_id = new_uuid()
    with store.db.transaction():
        store.db.insert_segmentation_set(
            seg_set_id,
            exp_id,
            cell_type["id"],
            "cellpose",
            fov_count=1,
            total_roi_count=2,
        )

    # Assign segmentation to FOV
    with store.db.transaction():
        store.db.assign_segmentation(
            [fov_id],
            seg_set_id,
            cell_type["id"],
            run_id,
            assigned_by="test",
        )

    # Create cell identities and ROIs
    cell_identity_1 = new_uuid()
    cell_identity_2 = new_uuid()
    roi_1 = new_uuid()
    roi_2 = new_uuid()
    with store.db.transaction():
        store.db.insert_cell_identity(cell_identity_1, fov_id, cell_type["id"])
        store.db.insert_cell_identity(cell_identity_2, fov_id, cell_type["id"])
        store.db.insert_roi(
            id=roi_1,
            fov_id=fov_id,
            roi_type_id=cell_type["id"],
            cell_identity_id=cell_identity_1,
            parent_roi_id=None,
            label_id=1,
            bbox_y=0, bbox_x=0, bbox_h=32, bbox_w=32,
            area_px=500,
        )
        store.db.insert_roi(
            id=roi_2,
            fov_id=fov_id,
            roi_type_id=cell_type["id"],
            cell_identity_id=cell_identity_2,
            parent_roi_id=None,
            label_id=2,
            bbox_y=32, bbox_x=32, bbox_h=32, bbox_w=32,
            area_px=300,
        )

    # Create a particle (sub-cellular ROI) under roi_1
    particle_id = new_uuid()
    with store.db.transaction():
        store.db.insert_roi(
            id=particle_id,
            fov_id=fov_id,
            roi_type_id=particle_type["id"],
            cell_identity_id=None,
            parent_roi_id=roi_1,
            label_id=100,
            bbox_y=5, bbox_x=5, bbox_h=10, bbox_w=10,
            area_px=50,
        )

    # Insert measurements
    with store.db.transaction():
        for roi_id in (roi_1, roi_2):
            for ch in channels:
                store.db.insert_measurement(
                    id=new_uuid(),
                    roi_id=roi_id,
                    channel_id=ch["id"],
                    metric="mean",
                    scope=SCOPE_WHOLE_ROI,
                    value=42.0,
                    pipeline_run_id=run_id,
                )

    return {
        "exp_id": exp_id,
        "cond_id": cond_id,
        "fov_id": fov_id,
        "fov_hex": fov_hex,
        "zarr_path": zarr_path,
        "channels": channels,
        "cell_type": cell_type,
        "particle_type": particle_type,
        "seg_set_id": seg_set_id,
        "run_id": run_id,
        "roi_1": roi_1,
        "roi_2": roi_2,
        "particle_id": particle_id,
        "cell_identity_1": cell_identity_1,
        "cell_identity_2": cell_identity_2,
    }


@pytest.fixture()
def populated_store(percell_dir: Path):
    """Create an ExperimentStore populated with FOV, ROIs, segmentation, etc."""
    store = ExperimentStore.create(percell_dir, SAMPLE_TOML)
    info = setup_populated_experiment(store)
    yield store, info
    store.close()
