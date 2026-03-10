"""ExperimentStore — public facade orchestrating ExperimentDB + LayerStore.

This is the ONLY public interface for PerCell 4 experiments.  External
code (CLI, napari, plugins) should never import ExperimentDB or LayerStore
directly; all access goes through ExperimentStore.

Responsibilities:
    - create / open / close experiment directories
    - startup recovery (stale staging, pending FOVs, incomplete deletions)
    - thin delegation to ExperimentDB and LayerStore for CRUD operations
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from percell4.core.config import ExperimentConfigV1
from percell4.core.constants import FovStatus
from percell4.core.db_types import new_uuid, uuid_to_str
from percell4.core.exceptions import ExperimentError
from percell4.core.experiment_db import ExperimentDB
from percell4.core.layer_store import LayerStore

logger = logging.getLogger(__name__)


class ExperimentStore:
    """Public API for CLI/napari. Orchestrates ExperimentDB + LayerStore.

    This is the ONLY public interface. External code should never
    import ExperimentDB or LayerStore directly.
    """

    def __init__(self, db: ExperimentDB, layers: LayerStore, root: Path):
        self._db = db
        self._layers = layers
        self._root = root

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def db(self) -> ExperimentDB:
        """Read-only access to DB layer for advanced queries."""
        return self._db

    @property
    def layers(self) -> LayerStore:
        """Read-only access to Zarr layer for advanced operations."""
        return self._layers

    @property
    def root(self) -> Path:
        return self._root

    # ------------------------------------------------------------------
    # Class methods: create / open
    # ------------------------------------------------------------------

    @classmethod
    def create(cls, path: Path, config_path: Path) -> ExperimentStore:
        """Create a new experiment in a .percell directory.

        Args:
            path: The .percell directory path to create.
            config_path: Path to the TOML configuration file.

        Returns:
            An open ExperimentStore ready for use.

        Raises:
            ExperimentError: If *path* already exists and contains files.
        """
        path = Path(path)

        if path.exists() and any(path.iterdir()):
            raise ExperimentError("Experiment already exists")

        layers = LayerStore.init_store(path)
        db = ExperimentDB(path / "experiment.db")
        db.open()

        config = ExperimentConfigV1.from_toml(config_path)
        config_hash = hashlib.sha256(config_path.read_bytes()).hexdigest()[:16]

        with db.transaction():
            experiment_id = new_uuid()
            db.insert_experiment(
                experiment_id, config.experiment.name, config_hash=config_hash
            )

            for ch in config.channels:
                db.insert_channel(
                    new_uuid(),
                    experiment_id,
                    ch.name,
                    ch.role,
                    ch.color,
                    ch.display_order,
                )

            # ROI types: two-pass to resolve parent references
            # First pass: insert types without a parent
            name_to_id: dict[str, bytes] = {}
            for rt in config.roi_types:
                if rt.parent_type is None:
                    rt_id = new_uuid()
                    db.insert_roi_type_definition(
                        rt_id, experiment_id, rt.name
                    )
                    name_to_id[rt.name] = rt_id

            # Second pass: insert types with a parent
            for rt in config.roi_types:
                if rt.parent_type is not None:
                    parent_id = name_to_id[rt.parent_type]
                    rt_id = new_uuid()
                    db.insert_roi_type_definition(
                        rt_id, experiment_id, rt.name, parent_type_id=parent_id
                    )
                    name_to_id[rt.name] = rt_id

        return cls(db, layers, path)

    @classmethod
    def open(cls, path: Path) -> ExperimentStore:
        """Open an existing experiment.

        Args:
            path: Path to the .percell directory.

        Returns:
            An open ExperimentStore with recovery already applied.

        Raises:
            ExperimentError: If the directory does not contain an experiment.db.
        """
        path = Path(path).resolve()

        db_path = path / "experiment.db"
        if not db_path.exists():
            raise ExperimentError(
                f"No experiment.db found at {path}"
            )

        db = ExperimentDB(db_path)
        db.open()
        layers = LayerStore(path)
        store = cls(db, layers, path)
        store._run_recovery()
        return store

    # ------------------------------------------------------------------
    # Lifecycle: close, context manager
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying database connection."""
        self._db.close()

    def __enter__(self) -> ExperimentStore:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Startup recovery
    # ------------------------------------------------------------------

    def _run_recovery(self) -> None:
        """Run startup recovery: clean staging, promote/error pending FOVs,
        complete deleting FOVs.

        Uses an atomic file lock with stale-lock detection (5 min timeout).
        """
        lock_path = self._root / ".recovery.lock"

        # Atomic lock acquisition
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
        except FileExistsError:
            # Stale lock detection
            try:
                if lock_path.stat().st_mtime < time.time() - 300:
                    lock_path.unlink()
                    fd = os.open(
                        str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY
                    )
                    os.close(fd)
                else:
                    logger.warning(
                        "Recovery lock held by another process, skipping"
                    )
                    return
            except FileExistsError:
                # Race condition: another process grabbed the lock
                logger.warning(
                    "Recovery lock held by another process, skipping"
                )
                return

        try:
            recovery_log: list[str] = []

            # 1. Clean old staging entries
            cleaned = self._layers.cleanup_pending(max_age_seconds=300.0)
            for p in cleaned:
                recovery_log.append(f"Cleaned staging: {p}")

            # 2. Handle pending FOVs
            exp = self._db.get_experiment()
            if exp:
                pending_fovs = self._db.get_fovs_by_status(
                    exp["id"], "pending"
                )
                for fov in pending_fovs:
                    with self._db.transaction():
                        if fov["zarr_path"] and self._layers.validate_zarr_group(
                            fov["zarr_path"]
                        ):
                            self._db.set_fov_status(
                                fov["id"],
                                FovStatus.imported,
                                "Promoted by recovery",
                            )
                            recovery_log.append(
                                f"Promoted pending FOV {uuid_to_str(fov['id'])}"
                            )
                        else:
                            self._db.set_fov_status(
                                fov["id"],
                                FovStatus.error,
                                "Invalid zarr detected by recovery",
                            )
                            recovery_log.append(
                                f"Marked FOV {uuid_to_str(fov['id'])} as error "
                                f"(invalid zarr)"
                            )

            # 3. Handle deleting FOVs
            if exp:
                deleting_fovs = self._db.get_fovs_by_status(
                    exp["id"], "deleting"
                )
                for fov in deleting_fovs:
                    if fov["zarr_path"]:
                        try:
                            self._layers.delete_path(fov["zarr_path"])
                        except Exception:
                            pass  # Already deleted or doesn't exist
                    with self._db.transaction():
                        self._db.set_fov_status(
                            fov["id"],
                            FovStatus.deleted,
                            "Completed by recovery",
                        )
                    recovery_log.append(
                        f"Completed deletion of FOV "
                        f"{uuid_to_str(fov['id'])}"
                    )

            # 4. Log recovery actions
            if recovery_log:
                log_path = self._root / "recovery.log"
                with open(log_path, "a") as f:
                    f.write(
                        f"\n--- Recovery "
                        f"{time.strftime('%Y-%m-%d %H:%M:%S')} ---\n"
                    )
                    for entry in recovery_log:
                        f.write(f"  {entry}\n")

                logger.info(
                    "Recovery: cleaned %d staging, processed %d FOVs",
                    len(cleaned),
                    len(recovery_log) - len(cleaned),
                )
        finally:
            lock_path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Delegated methods: FOV operations
    # ------------------------------------------------------------------

    def insert_fov(self, **kwargs: Any) -> int:
        """Insert an FOV record. See ExperimentDB.insert_fov."""
        return self._db.insert_fov(**kwargs)

    def get_fov(self, fov_id: bytes) -> Any:
        """Return a single FOV by ID."""
        return self._db.get_fov(fov_id)

    def get_fovs(self, experiment_id: bytes) -> list[Any]:
        """Return all FOVs for an experiment."""
        return self._db.get_fovs(experiment_id)

    def get_fovs_by_status(
        self, experiment_id: bytes, status: str
    ) -> list[Any]:
        """Return FOVs filtered by status."""
        return self._db.get_fovs_by_status(experiment_id, status)

    # ------------------------------------------------------------------
    # Delegated methods: Status
    # ------------------------------------------------------------------

    def get_fov_status(self, fov_id: bytes) -> str:
        """Return the current status of an FOV."""
        return self._db.get_fov_status(fov_id)

    def set_fov_status(
        self,
        fov_id: bytes,
        new_status: str,
        message: str | None = None,
    ) -> None:
        """Transition an FOV to a new status."""
        return self._db.set_fov_status(fov_id, new_status, message)

    # ------------------------------------------------------------------
    # Delegated methods: Assignments
    # ------------------------------------------------------------------

    def assign_segmentation(self, *args: Any, **kwargs: Any) -> Any:
        """Assign a segmentation set to FOVs."""
        return self._db.assign_segmentation(*args, **kwargs)

    def assign_mask(self, *args: Any, **kwargs: Any) -> Any:
        """Assign a threshold mask to FOVs."""
        return self._db.assign_mask(*args, **kwargs)

    def get_active_assignments(self, fov_id: bytes) -> dict[str, list[Any]]:
        """Return all active assignments for an FOV."""
        return self._db.get_active_assignments(fov_id)

    # ------------------------------------------------------------------
    # Delegated methods: Measurements
    # ------------------------------------------------------------------

    def get_active_measurements(self, fov_id: bytes) -> list[Any]:
        """Return measurements filtered through active assignments."""
        return self._db.get_active_measurements(fov_id)

    # ------------------------------------------------------------------
    # Delegated methods: Merge
    # ------------------------------------------------------------------

    def merge_experiment(self, source_path: Path) -> dict[str, Any]:
        """Merge another .percell database into this one."""
        return self._db.merge_experiment(source_path)

    # ------------------------------------------------------------------
    # Delegated methods: Lineage
    # ------------------------------------------------------------------

    def get_descendants(self, fov_id: bytes) -> list[Any]:
        """Return all descendant FOV rows."""
        return self._db.get_descendants(fov_id)

    def get_ancestors(self, fov_id: bytes) -> list[Any]:
        """Return all ancestor FOV rows."""
        return self._db.get_ancestors(fov_id)

    # ------------------------------------------------------------------
    # Delegated methods: Channels, conditions, experiment
    # ------------------------------------------------------------------

    def get_channels(self, experiment_id: bytes) -> list[Any]:
        """Return all channels for an experiment."""
        return self._db.get_channels(experiment_id)

    def get_conditions(self, experiment_id: bytes) -> list[Any]:
        """Return all conditions for an experiment."""
        return self._db.get_conditions(experiment_id)

    def get_experiment(self) -> Any:
        """Return the first experiment record."""
        return self._db.get_experiment()

    # ------------------------------------------------------------------
    # Transaction access for advanced use
    # ------------------------------------------------------------------

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Transaction context manager, delegating to ExperimentDB."""
        with self._db.transaction():
            yield
