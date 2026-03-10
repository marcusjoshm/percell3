"""Tests for ExperimentStore — the public facade.

Covers create/open/close, startup recovery, delegated methods,
derived FOV creation, soft-delete, measurement dispatch,
ROI cell identity enforcement, CSV export,
and the boundary constraint (no direct sqlite3/zarr imports).
"""

from __future__ import annotations

import ast
import csv
import json
import os
import time
from pathlib import Path

import numpy as np
import pytest
import zarr

from percell4.core.constants import FovStatus, SCOPE_DISPLAY, SCOPE_WHOLE_ROI
from percell4.core.db_types import new_uuid, uuid_to_hex, uuid_to_str
from percell4.core.exceptions import ExperimentError
from percell4.core.experiment_store import ExperimentStore
from percell4.core.models import MeasurementNeeded

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
SAMPLE_TOML = FIXTURES_DIR / "sample_experiment.toml"


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
# 1. test_create_experiment
# ---------------------------------------------------------------------------


def test_create_experiment(percell_dir: Path) -> None:
    """Creates .percell dir with experiment.db and zarr structure."""
    store = ExperimentStore.create(percell_dir, SAMPLE_TOML)
    try:
        assert (percell_dir / "experiment.db").exists()
        assert (percell_dir / "zarr" / "images").is_dir()
        assert (percell_dir / "zarr" / "segmentations").is_dir()
        assert (percell_dir / "zarr" / "masks").is_dir()
        assert store.root == percell_dir
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 2. test_create_populates_channels
# ---------------------------------------------------------------------------


def test_create_populates_channels(created_store: ExperimentStore) -> None:
    """Channels from TOML are present in DB."""
    exp = created_store.get_experiment()
    channels = created_store.get_channels(exp["id"])
    names = {ch["name"] for ch in channels}
    assert names == {"DAPI", "GFP"}


# ---------------------------------------------------------------------------
# 3. test_create_populates_roi_types
# ---------------------------------------------------------------------------


def test_create_populates_roi_types(created_store: ExperimentStore) -> None:
    """roi_type_definitions from TOML are present in DB."""
    exp = created_store.get_experiment()
    roi_types = created_store.db.get_roi_type_definitions(exp["id"])
    names = {rt["name"] for rt in roi_types}
    assert names == {"cell", "particle"}


# ---------------------------------------------------------------------------
# 4. test_create_with_hierarchy
# ---------------------------------------------------------------------------


def test_create_with_hierarchy(created_store: ExperimentStore) -> None:
    """parent_type references resolved (particle -> cell)."""
    exp = created_store.get_experiment()
    roi_types = created_store.db.get_roi_type_definitions(exp["id"])

    type_map = {rt["name"]: rt for rt in roi_types}
    cell_type = type_map["cell"]
    particle_type = type_map["particle"]

    assert cell_type["parent_type_id"] is None
    assert particle_type["parent_type_id"] == cell_type["id"]


# ---------------------------------------------------------------------------
# 5. test_create_config_hash_stored
# ---------------------------------------------------------------------------


def test_create_config_hash_stored(created_store: ExperimentStore) -> None:
    """Experiment record has config_hash."""
    exp = created_store.get_experiment()
    assert exp["config_hash"] is not None
    assert len(exp["config_hash"]) == 16  # sha256 hex truncated to 16


# ---------------------------------------------------------------------------
# 6. test_create_existing_raises
# ---------------------------------------------------------------------------


def test_create_existing_raises(percell_dir: Path) -> None:
    """Creating over existing experiment raises ExperimentError."""
    store = ExperimentStore.create(percell_dir, SAMPLE_TOML)
    store.close()

    with pytest.raises(ExperimentError, match="already exists"):
        ExperimentStore.create(percell_dir, SAMPLE_TOML)


# ---------------------------------------------------------------------------
# 7. test_open_existing
# ---------------------------------------------------------------------------


def test_open_existing(percell_dir: Path) -> None:
    """Open previously created experiment."""
    store = ExperimentStore.create(percell_dir, SAMPLE_TOML)
    exp_id = store.get_experiment()["id"]
    store.close()

    store2 = ExperimentStore.open(percell_dir)
    try:
        exp2 = store2.get_experiment()
        assert exp2["id"] == exp_id
    finally:
        store2.close()


# ---------------------------------------------------------------------------
# 8. test_open_nonexistent_raises
# ---------------------------------------------------------------------------


def test_open_nonexistent_raises(tmp_path: Path) -> None:
    """Opening nonexistent path raises ExperimentError."""
    with pytest.raises(ExperimentError, match="No experiment.db"):
        ExperimentStore.open(tmp_path / "does_not_exist.percell")


# ---------------------------------------------------------------------------
# 9. test_context_manager
# ---------------------------------------------------------------------------


def test_context_manager(percell_dir: Path) -> None:
    """__enter__/__exit__ work correctly."""
    store = ExperimentStore.create(percell_dir, SAMPLE_TOML)
    store.close()

    with ExperimentStore.open(percell_dir) as s:
        exp = s.get_experiment()
        assert exp is not None

    # After context manager exit, DB should be closed
    # Accessing connection should raise
    assert s.db._conn is None


# ---------------------------------------------------------------------------
# 10. test_recovery_cleans_old_pending
# ---------------------------------------------------------------------------


def test_recovery_cleans_old_pending(percell_dir: Path) -> None:
    """Old .pending entries removed on open."""
    store = ExperimentStore.create(percell_dir, SAMPLE_TOML)
    store.close()

    # Create a stale pending entry
    pending_dir = percell_dir / "zarr" / ".pending" / "stale_entry"
    pending_dir.mkdir(parents=True)
    (pending_dir / "data").write_text("test")

    # Age the entry
    old_time = time.time() - 600
    os.utime(str(pending_dir), (old_time, old_time))

    with ExperimentStore.open(percell_dir):
        pass

    assert not pending_dir.exists()


# ---------------------------------------------------------------------------
# 11. test_recovery_promotes_valid_pending_fov
# ---------------------------------------------------------------------------


def test_recovery_promotes_valid_pending_fov(percell_dir: Path) -> None:
    """Pending FOV with valid zarr becomes imported."""
    store = ExperimentStore.create(percell_dir, SAMPLE_TOML)
    exp = store.get_experiment()

    # Create a pending FOV with a valid zarr path
    fov_id = new_uuid()
    zarr_path = "zarr/images/test_fov"
    with store.transaction():
        store.insert_fov(
            id=fov_id,
            experiment_id=exp["id"],
            status="pending",
            zarr_path=zarr_path,
        )

    # Write valid zarr data
    full_path = percell_dir / zarr_path
    full_path.mkdir(parents=True, exist_ok=True)
    group = zarr.open_group(str(full_path), mode="w")
    group.array("0", data=np.zeros((10, 10), dtype=np.uint16))

    store.close()

    # Re-open triggers recovery
    store2 = ExperimentStore.open(percell_dir)
    try:
        status = store2.get_fov_status(fov_id)
        assert status == "imported"
    finally:
        store2.close()


# ---------------------------------------------------------------------------
# 12. test_recovery_handles_deleting_fov
# ---------------------------------------------------------------------------


def test_recovery_handles_deleting_fov(percell_dir: Path) -> None:
    """Deleting FOV gets completed on recovery."""
    store = ExperimentStore.create(percell_dir, SAMPLE_TOML)
    exp = store.get_experiment()

    # Create a FOV and advance it to deleting status
    fov_id = new_uuid()
    zarr_path = "zarr/images/to_delete"
    with store.transaction():
        store.insert_fov(
            id=fov_id,
            experiment_id=exp["id"],
            status="pending",
            zarr_path=zarr_path,
        )
        # pending -> imported -> deleting
        store.set_fov_status(fov_id, FovStatus.imported, "test")
        store.set_fov_status(fov_id, FovStatus.deleting, "test")

    # Create the zarr directory so delete_path can clean it
    full_path = percell_dir / zarr_path
    full_path.mkdir(parents=True, exist_ok=True)
    (full_path / "data").write_text("test")

    store.close()

    # Re-open triggers recovery
    store2 = ExperimentStore.open(percell_dir)
    try:
        status = store2.get_fov_status(fov_id)
        assert status == "deleted"
        # Zarr data should be deleted
        assert not full_path.exists()
    finally:
        store2.close()


# ---------------------------------------------------------------------------
# 13. test_recovery_lock_released_on_error
# ---------------------------------------------------------------------------


def test_recovery_lock_released_on_error(
    percell_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lock file cleaned up on exception during recovery."""
    store = ExperimentStore.create(percell_dir, SAMPLE_TOML)
    store.close()

    lock_path = percell_dir / ".recovery.lock"

    # Monkeypatch cleanup_pending to raise
    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    store2 = ExperimentStore.__new__(ExperimentStore)
    db = ExperimentStore.open.__func__  # type: ignore[attr-defined]

    # Open the store, but make recovery fail
    from percell4.core.experiment_db import ExperimentDB
    from percell4.core.layer_store import LayerStore

    db_obj = ExperimentDB(percell_dir / "experiment.db")
    db_obj.open()
    layers_obj = LayerStore(percell_dir)
    store2 = ExperimentStore(db_obj, layers_obj, percell_dir)

    monkeypatch.setattr(layers_obj, "cleanup_pending", _boom)

    with pytest.raises(RuntimeError, match="boom"):
        store2._run_recovery()

    store2.close()

    assert not lock_path.exists()


# ---------------------------------------------------------------------------
# 14. test_recovery_stale_lock_removed
# ---------------------------------------------------------------------------


def test_recovery_stale_lock_removed(percell_dir: Path) -> None:
    """Lock older than 5 min is removed and recovery proceeds."""
    store = ExperimentStore.create(percell_dir, SAMPLE_TOML)
    store.close()

    # Create a stale lock file
    lock_path = percell_dir / ".recovery.lock"
    lock_path.touch()
    old_time = time.time() - 600  # 10 min old
    os.utime(str(lock_path), (old_time, old_time))

    # Open should succeed (stale lock removed)
    with ExperimentStore.open(percell_dir) as s:
        assert s.get_experiment() is not None

    assert not lock_path.exists()


# ---------------------------------------------------------------------------
# 15. test_delegated_methods_work
# ---------------------------------------------------------------------------


def test_delegated_methods_work(created_store: ExperimentStore) -> None:
    """Basic smoke test for get_experiment, get_channels, etc."""
    store = created_store

    # get_experiment
    exp = store.get_experiment()
    assert exp is not None
    assert exp["name"] == "Test Experiment"

    # get_channels
    channels = store.get_channels(exp["id"])
    assert len(channels) == 2

    # get_conditions (empty initially)
    conditions = store.get_conditions(exp["id"])
    assert conditions == []

    # get_fovs (empty initially)
    fovs = store.get_fovs(exp["id"])
    assert fovs == []

    # transaction context manager
    fov_id = new_uuid()
    with store.transaction():
        store.insert_fov(id=fov_id, experiment_id=exp["id"])

    fov = store.get_fov(fov_id)
    assert fov is not None
    assert fov["status"] == "pending"

    # get_fovs_by_status
    pending = store.get_fovs_by_status(exp["id"], "pending")
    assert len(pending) == 1

    # get_fov_status / set_fov_status
    assert store.get_fov_status(fov_id) == "pending"
    store.set_fov_status(fov_id, FovStatus.imported, "test")
    assert store.get_fov_status(fov_id) == "imported"

    # get_descendants / get_ancestors (empty for single FOV)
    assert store.get_descendants(fov_id) == []
    assert store.get_ancestors(fov_id) == []


# ---------------------------------------------------------------------------
# 16. test_boundary_no_sqlite3_no_zarr
# ---------------------------------------------------------------------------


def test_boundary_no_sqlite3_no_zarr() -> None:
    """AST scan: experiment_store.py must NOT import sqlite3 or zarr."""
    source_path = (
        Path(__file__).resolve().parent.parent.parent.parent
        / "src"
        / "percell4"
        / "core"
        / "experiment_store.py"
    )
    source = source_path.read_text()
    tree = ast.parse(source)

    forbidden = {"sqlite3", "zarr"}
    imported: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module.split(".")[0])

    violations = forbidden & imported
    assert not violations, (
        f"experiment_store.py imports forbidden modules: {violations}"
    )


# ---------------------------------------------------------------------------
# Recovery edge case: pending FOV without zarr_path gets marked error
# ---------------------------------------------------------------------------


def test_recovery_marks_pending_without_zarr_as_error(
    percell_dir: Path,
) -> None:
    """Pending FOV without valid zarr_path is marked as error."""
    store = ExperimentStore.create(percell_dir, SAMPLE_TOML)
    exp = store.get_experiment()

    fov_id = new_uuid()
    with store.transaction():
        store.insert_fov(
            id=fov_id,
            experiment_id=exp["id"],
            status="pending",
            zarr_path=None,
        )
    store.close()

    store2 = ExperimentStore.open(percell_dir)
    try:
        status = store2.get_fov_status(fov_id)
        assert status == "error"
    finally:
        store2.close()


# ===========================================================================
# Helper: create a fully populated experiment for derived FOV tests
# ===========================================================================


def _setup_populated_experiment(store: ExperimentStore) -> dict:
    """Create an experiment with FOV, channels, segmentation, ROIs, and measurements.

    Returns a dict with all entity IDs for use in tests.
    """
    exp = store.get_experiment()
    exp_id = exp["id"]
    channels = store.get_channels(exp_id)
    roi_types = store.db.get_roi_type_definitions(exp_id)

    type_map = {rt["name"]: rt for rt in roi_types}
    cell_type = type_map["cell"]
    particle_type = type_map["particle"]

    # Create a condition
    cond_id = new_uuid()
    with store.transaction():
        store.db.insert_condition(cond_id, exp_id, "control")

    # Create source FOV with zarr data
    fov_id = new_uuid()
    fov_hex = uuid_to_hex(fov_id)
    channel_arrays = {
        0: np.ones((64, 64), dtype=np.uint16) * 100,
        1: np.ones((64, 64), dtype=np.uint16) * 200,
    }
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
            seg_set_id,
            exp_id,
            cell_type["id"],
            "cellpose",
            fov_count=1,
            total_roi_count=2,
        )

    # Assign segmentation to FOV
    with store.transaction():
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
    with store.transaction():
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
    with store.transaction():
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
    with store.transaction():
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
    info = _setup_populated_experiment(store)
    yield store, info
    store.close()


# ===========================================================================
# Derived FOV Tests
# ===========================================================================


# ---------------------------------------------------------------------------
# 17. test_create_derived_fov
# ---------------------------------------------------------------------------


def test_create_derived_fov(populated_store) -> None:
    """Creates derived FOV, verify it exists in DB with correct parent, op, params."""
    store, info = populated_store

    def identity_transform(arrays):
        return arrays

    derived_id = store.create_derived_fov(
        source_fov_id=info["fov_id"],
        derivation_op="nan_zero",
        params={"threshold": 0},
        transform_fn=identity_transform,
    )

    derived = store.get_fov(derived_id)
    assert derived is not None
    assert derived["parent_fov_id"] == info["fov_id"]
    assert derived["derivation_op"] == "nan_zero"
    assert json.loads(derived["derivation_params"]) == {"threshold": 0}
    assert derived["experiment_id"] == info["exp_id"]
    assert derived["condition_id"] == info["cond_id"]
    assert derived["status"] == "imported"


# ---------------------------------------------------------------------------
# 18. test_create_derived_fov_copies_assignments
# ---------------------------------------------------------------------------


def test_create_derived_fov_copies_assignments(populated_store) -> None:
    """Active seg assignments are copied to derived FOV."""
    store, info = populated_store

    derived_id = store.create_derived_fov(
        source_fov_id=info["fov_id"],
        derivation_op="bg_sub",
        params={},
        transform_fn=lambda a: a,
    )

    active = store.get_active_assignments(derived_id)
    assert len(active["segmentation"]) >= 1
    seg = active["segmentation"][0]
    assert seg["segmentation_set_id"] == info["seg_set_id"]
    assert seg["assigned_by"] == "derived_fov"


# ---------------------------------------------------------------------------
# 19. test_create_derived_fov_duplicates_top_level_rois
# ---------------------------------------------------------------------------


def test_create_derived_fov_duplicates_top_level_rois(populated_store) -> None:
    """Top-level ROIs are duplicated with new UUIDs, same cell_identity_id."""
    store, info = populated_store

    derived_id = store.create_derived_fov(
        source_fov_id=info["fov_id"],
        derivation_op="test_op",
        params={},
        transform_fn=lambda a: a,
    )

    derived_cells = store.db.get_cells(derived_id)
    assert len(derived_cells) == 2

    # New UUIDs but same cell identities
    derived_ids = {c["id"] for c in derived_cells}
    assert info["roi_1"] not in derived_ids
    assert info["roi_2"] not in derived_ids

    derived_identities = {c["cell_identity_id"] for c in derived_cells}
    assert info["cell_identity_1"] in derived_identities
    assert info["cell_identity_2"] in derived_identities


# ---------------------------------------------------------------------------
# 20. test_create_derived_fov_skips_subcellular_rois
# ---------------------------------------------------------------------------


def test_create_derived_fov_skips_subcellular_rois(populated_store) -> None:
    """Particles (sub-cellular ROIs) are NOT duplicated."""
    store, info = populated_store

    derived_id = store.create_derived_fov(
        source_fov_id=info["fov_id"],
        derivation_op="test_op",
        params={},
        transform_fn=lambda a: a,
    )

    # Get all ROIs for the derived FOV
    all_rois = store.db.get_rois(derived_id)
    # Only top-level (cells), no particles
    for roi in all_rois:
        assert roi["roi_type_id"] == info["cell_type"]["id"]


# ---------------------------------------------------------------------------
# 21. test_create_derived_fov_auto_name
# ---------------------------------------------------------------------------


def test_create_derived_fov_auto_name(populated_store) -> None:
    """auto_name is '{source}_{op}'."""
    store, info = populated_store

    derived_id = store.create_derived_fov(
        source_fov_id=info["fov_id"],
        derivation_op="nan_zero",
        params={},
        transform_fn=lambda a: a,
    )

    derived = store.get_fov(derived_id)
    assert derived["auto_name"] == "FOV_001_nan_zero"


# ---------------------------------------------------------------------------
# 22. test_create_derived_fov_zarr_written
# ---------------------------------------------------------------------------


def test_create_derived_fov_zarr_written(populated_store) -> None:
    """zarr data is readable from LayerStore after derivation."""
    store, info = populated_store

    def double_transform(arrays):
        return {k: v * 2 for k, v in arrays.items()}

    derived_id = store.create_derived_fov(
        source_fov_id=info["fov_id"],
        derivation_op="double",
        params={},
        transform_fn=double_transform,
    )

    derived_hex = uuid_to_hex(derived_id)
    ch0 = store.layers.read_image_channel_numpy(derived_hex, 0)
    ch1 = store.layers.read_image_channel_numpy(derived_hex, 1)

    # Original was 100 and 200, doubled should be 200 and 400
    assert ch0[0, 0] == 200
    assert ch1[0, 0] == 400


# ===========================================================================
# Soft-delete Tests
# ===========================================================================


# ---------------------------------------------------------------------------
# 23. test_delete_fov_soft_delete
# ---------------------------------------------------------------------------


def test_delete_fov_soft_delete(populated_store) -> None:
    """Status transitions deleting -> deleted, zarr removed."""
    store, info = populated_store
    fov_id = info["fov_id"]

    # Advance to a deletable status (imported -> deleting -> deleted)
    store.delete_fov(fov_id)

    status = store.get_fov_status(fov_id)
    assert status == "deleted"

    # Zarr should be gone
    zarr_full = store.root / info["zarr_path"]
    assert not zarr_full.exists()


# ---------------------------------------------------------------------------
# 24. test_delete_fov_no_zarr
# ---------------------------------------------------------------------------


def test_delete_fov_no_zarr(percell_dir: Path) -> None:
    """Works when zarr_path is None."""
    store = ExperimentStore.create(percell_dir, SAMPLE_TOML)
    try:
        exp = store.get_experiment()
        fov_id = new_uuid()
        with store.transaction():
            store.insert_fov(
                id=fov_id,
                experiment_id=exp["id"],
                status="pending",
                zarr_path=None,
            )
            store.set_fov_status(fov_id, FovStatus.imported, "test")

        store.delete_fov(fov_id)
        assert store.get_fov_status(fov_id) == "deleted"
    finally:
        store.close()


# ===========================================================================
# Mark descendants stale
# ===========================================================================


# ---------------------------------------------------------------------------
# 25. test_mark_descendants_stale
# ---------------------------------------------------------------------------


def test_mark_descendants_stale(populated_store) -> None:
    """Derived FOV is marked stale when parent is modified."""
    store, info = populated_store

    # Create a derived FOV
    derived_id = store.create_derived_fov(
        source_fov_id=info["fov_id"],
        derivation_op="test",
        params={},
        transform_fn=lambda a: a,
    )
    assert store.get_fov_status(derived_id) == "imported"

    # Mark descendants stale
    count = store.mark_descendants_stale(info["fov_id"])
    assert count == 1
    assert store.get_fov_status(derived_id) == "stale"


# ===========================================================================
# insert_roi_checked Tests
# ===========================================================================


# ---------------------------------------------------------------------------
# 26. test_insert_roi_checked_top_level_requires_identity
# ---------------------------------------------------------------------------


def test_insert_roi_checked_top_level_requires_identity(
    populated_store,
) -> None:
    """Raises without cell_identity_id for top-level ROI."""
    store, info = populated_store

    with pytest.raises(ExperimentError, match="require a cell_identity_id"):
        store.insert_roi_checked(
            id=new_uuid(),
            fov_id=info["fov_id"],
            roi_type_id=info["cell_type"]["id"],
            cell_identity_id=None,
            parent_roi_id=None,
            label_id=99,
            bbox_y=0, bbox_x=0, bbox_h=10, bbox_w=10,
            area_px=100,
        )


# ---------------------------------------------------------------------------
# 27. test_insert_roi_checked_subcellular_requires_parent
# ---------------------------------------------------------------------------


def test_insert_roi_checked_subcellular_requires_parent(
    populated_store,
) -> None:
    """Raises without parent_roi_id for sub-cellular ROI."""
    store, info = populated_store

    with pytest.raises(ExperimentError, match="require a parent_roi_id"):
        store.insert_roi_checked(
            id=new_uuid(),
            fov_id=info["fov_id"],
            roi_type_id=info["particle_type"]["id"],
            cell_identity_id=None,
            parent_roi_id=None,
            label_id=99,
            bbox_y=0, bbox_x=0, bbox_h=10, bbox_w=10,
            area_px=100,
        )


# ---------------------------------------------------------------------------
# 28. test_insert_roi_checked_subcellular_rejects_identity
# ---------------------------------------------------------------------------


def test_insert_roi_checked_subcellular_rejects_identity(
    populated_store,
) -> None:
    """Raises with cell_identity_id for sub-cellular ROI."""
    store, info = populated_store

    with pytest.raises(
        ExperimentError, match="must have NULL cell_identity_id"
    ):
        store.insert_roi_checked(
            id=new_uuid(),
            fov_id=info["fov_id"],
            roi_type_id=info["particle_type"]["id"],
            cell_identity_id=info["cell_identity_1"],
            parent_roi_id=info["roi_1"],
            label_id=99,
            bbox_y=0, bbox_x=0, bbox_h=10, bbox_w=10,
            area_px=100,
        )


# ---------------------------------------------------------------------------
# 29. test_insert_roi_checked_valid_top_level
# ---------------------------------------------------------------------------


def test_insert_roi_checked_valid_top_level(populated_store) -> None:
    """Succeeds with cell_identity_id for top-level ROI."""
    store, info = populated_store

    new_ci = new_uuid()
    with store.transaction():
        store.db.insert_cell_identity(
            new_ci, info["fov_id"], info["cell_type"]["id"]
        )

    result = store.insert_roi_checked(
        id=new_uuid(),
        fov_id=info["fov_id"],
        roi_type_id=info["cell_type"]["id"],
        cell_identity_id=new_ci,
        parent_roi_id=None,
        label_id=99,
        bbox_y=0, bbox_x=0, bbox_h=10, bbox_w=10,
        area_px=100,
    )
    assert result == 1


# ---------------------------------------------------------------------------
# 30. test_insert_roi_checked_valid_subcellular
# ---------------------------------------------------------------------------


def test_insert_roi_checked_valid_subcellular(populated_store) -> None:
    """Succeeds with parent_roi_id for sub-cellular ROI."""
    store, info = populated_store

    result = store.insert_roi_checked(
        id=new_uuid(),
        fov_id=info["fov_id"],
        roi_type_id=info["particle_type"]["id"],
        cell_identity_id=None,
        parent_roi_id=info["roi_1"],
        label_id=99,
        bbox_y=0, bbox_x=0, bbox_h=10, bbox_w=10,
        area_px=100,
    )
    assert result == 1


# ===========================================================================
# dispatch_measurements
# ===========================================================================


# ---------------------------------------------------------------------------
# 31. test_dispatch_measurements_returns_count
# ---------------------------------------------------------------------------


def test_dispatch_measurements_returns_count(populated_store) -> None:
    """Returns correct count of measurement items."""
    store, info = populated_store

    needed = [
        MeasurementNeeded(
            fov_id=info["fov_id"],
            roi_type_id=info["cell_type"]["id"],
            channel_ids=[ch["id"] for ch in info["channels"]],
            reason="new_assignment",
        ),
        MeasurementNeeded(
            fov_id=info["fov_id"],
            roi_type_id=info["cell_type"]["id"],
            channel_ids=[ch["id"] for ch in info["channels"]],
            reason="reassignment",
        ),
    ]
    count = store.dispatch_measurements(needed)
    assert count == 2


# ===========================================================================
# export_measurements_csv
# ===========================================================================


# ---------------------------------------------------------------------------
# 32. test_export_csv_basic
# ---------------------------------------------------------------------------


def test_export_csv_basic(populated_store, tmp_path: Path) -> None:
    """Exports measurements to CSV, verify file content."""
    store, info = populated_store

    output = tmp_path / "export.csv"
    count = store.export_measurements_csv([info["fov_id"]], output)

    # 2 ROIs x 2 channels x 1 metric = 4 rows
    assert count == 4
    assert output.exists()

    with open(output) as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 4
    # Check header fields
    assert "fov_id" in rows[0]
    assert "roi_id" in rows[0]
    assert "channel_id" in rows[0]
    assert "metric" in rows[0]
    assert "scope" in rows[0]
    assert "value" in rows[0]

    # Check scope is human-readable
    for row in rows:
        assert row["scope"] == SCOPE_DISPLAY.get(SCOPE_WHOLE_ROI, SCOPE_WHOLE_ROI)
