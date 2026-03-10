"""Tests for ExperimentStore — the public facade.

Covers create/open/close, startup recovery, delegated methods,
and the boundary constraint (no direct sqlite3/zarr imports).
"""

from __future__ import annotations

import ast
import os
import time
from pathlib import Path

import numpy as np
import pytest
import zarr

from percell4.core.constants import FovStatus
from percell4.core.db_types import new_uuid, uuid_to_str
from percell4.core.exceptions import ExperimentError
from percell4.core.experiment_store import ExperimentStore

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
