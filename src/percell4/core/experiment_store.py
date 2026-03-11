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
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

from percell4.core.config import ExperimentConfigV1
from percell4.core.constants import FovStatus
from percell4.core.db_types import new_uuid, uuid_to_hex, uuid_to_str
from percell4.core.exceptions import ExperimentError
from percell4.core.experiment_db import ExperimentDB
from percell4.core.layer_store import LayerStore
from percell4.core.models import MeasurementNeeded

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Utility: channel-index lookup
# ---------------------------------------------------------------------------


def find_channel_index(
    channels: list[dict],
    *,
    channel_id: bytes | None = None,
    channel_name: str | None = None,
) -> int:
    """Find a channel's positional index by ID or name.

    Args:
        channels: List of channel dicts (as returned by ``db.get_channels``).
        channel_id: Match by ``ch["id"]`` (UUID bytes).
        channel_name: Match by ``ch["name"]`` (string).

    Returns:
        Zero-based index of the matching channel.

    Raises:
        ValueError: If no channel matches the given criteria.
    """
    for idx, ch in enumerate(channels):
        if channel_id is not None and ch["id"] == channel_id:
            return idx
        if channel_name is not None and ch["name"] == channel_name:
            return idx
    raise ValueError(f"Channel not found: id={channel_id}, name={channel_name}")


class ExperimentStore:
    """Public API for CLI/napari. Orchestrates ExperimentDB + LayerStore.

    This is the ONLY public interface. External code should never
    import ExperimentDB or LayerStore directly.

    Viewer module scope note (schema 6.0.0):
        The viewer module has 37 ``store.db.*`` calls across 6 files.
        The following may need updating for lineage/derived FOV features:

        - ``_viewer.py``: get_fovs (may need lineage_depth display),
          get_fov (may need display_name fallback),
          insert_segmentation_set / assign_segmentation (no changes needed)
        - ``fov_browser_widget.py``: get_fovs (may want to show lineage tree,
          display_name, filter by lineage_depth)
        - ``measurement_widget.py``: get_active_measurements (no changes needed,
          measurements.value is already nullable for NaN)
        - ``group_threshold_widget.py``: get_intensity_groups (no changes needed)

        These are cosmetic/UX updates, NOT functional breakage.
        No viewer changes are required for correctness.
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
    def create(
        cls,
        path: Path,
        config_path: Path | None = None,
        *,
        name: str = "",
        description: str = "",
        overwrite: bool = False,
    ) -> ExperimentStore:
        """Create a new experiment in a .percell directory.

        Experiments can be created two ways:

        - **Interactive (default):** Just provide *name*.  Channels and
          ROI types are added later during import.
        - **From TOML config:** Provide *config_path* to pre-populate
          channels and ROI types from a config file (useful for scripting
          and tests).

        Args:
            path: The .percell directory path to create.
            config_path: Optional TOML config file for pre-populating
                channels and ROI types.
            name: Human-readable experiment name (used when no config).
            description: Experiment description.
            overwrite: If True, remove existing non-empty directory first.

        Returns:
            An open ExperimentStore ready for use.

        Raises:
            ExperimentError: If *path* already exists and is non-empty
                (unless *overwrite* is True).
        """
        import shutil

        path = Path(path)

        if path.exists() and any(path.iterdir()):
            if not overwrite:
                raise ExperimentError(
                    f"Directory is not empty: {path}  "
                    "(use overwrite=True to replace)"
                )
            shutil.rmtree(path)
            path.mkdir(parents=True)
        elif not path.exists():
            path.mkdir(parents=True)

        layers = LayerStore.init_store(path)
        db = ExperimentDB(path / "experiment.db")
        db.open()

        with db.transaction():
            experiment_id = new_uuid()

            if config_path is not None:
                # TOML-based creation: pre-populate channels and ROI types
                config = ExperimentConfigV1.from_toml(config_path)
                config_hash = hashlib.sha256(
                    config_path.read_bytes()
                ).hexdigest()[:16]
                db.insert_experiment(
                    experiment_id,
                    config.experiment.name,
                    config_hash=config_hash,
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
                name_to_id: dict[str, bytes] = {}
                for rt in config.roi_types:
                    if rt.parent_type is None:
                        rt_id = new_uuid()
                        db.insert_roi_type_definition(
                            rt_id, experiment_id, rt.name
                        )
                        name_to_id[rt.name] = rt_id
                for rt in config.roi_types:
                    if rt.parent_type is not None:
                        parent_id = name_to_id[rt.parent_type]
                        rt_id = new_uuid()
                        db.insert_roi_type_definition(
                            rt_id, experiment_id, rt.name,
                            parent_type_id=parent_id,
                        )
                        name_to_id[rt.name] = rt_id
            else:
                # Interactive creation: empty experiment, channels added at import
                db.insert_experiment(experiment_id, name or "Untitled")

                # Always create a default "cell" ROI type
                db.insert_roi_type_definition(
                    new_uuid(), experiment_id, "cell"
                )

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

        # Schema version check and migration
        from percell4.core.migration import (
            SCHEMA_VERSION,
            get_schema_version,
            run_migrations,
        )

        current = get_schema_version(db.connection)
        if current != SCHEMA_VERSION:
            applied = run_migrations(db.connection, current, SCHEMA_VERSION)
            if applied:
                db.connection.commit()

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
    # Delegated methods: Merge
    # ------------------------------------------------------------------

    def merge_experiment(self, source_path: Path) -> dict[str, Any]:
        """Merge another .percell database into this one."""
        return self._db.merge_experiment(source_path)

    # ------------------------------------------------------------------
    # Derived FOV creation
    # ------------------------------------------------------------------

    def create_derived_fov(
        self,
        source_fov_id: bytes,
        derivation_op: str,
        params: dict,
        transform_fn: Callable[[dict[int, np.ndarray]], dict[int, np.ndarray]],
        *,
        display_name: str | None = None,
        channel_metadata: str | None = None,
        pipeline_run_id: bytes | None = None,
    ) -> bytes:
        """Create a derived FOV using the four-step contract.

        The entire DB operation (insert FOV, copy assignments, duplicate
        ROIs, set status) is wrapped in a single transaction for atomicity.

        Args:
            source_fov_id: ID of the source FOV.
            derivation_op: Name of the operation (e.g., 'bg_subtraction').
            params: Operation parameters (serialized to JSON in DB).
            transform_fn: Pure function that takes channel arrays and returns
                modified arrays.
                Signature: dict[channel_index, ndarray] -> dict[channel_index, ndarray]
            display_name: Optional user-facing name for the derived FOV.
            channel_metadata: Optional JSON string of per-channel metadata.
            pipeline_run_id: Optional pipeline run ID that created this FOV.

        Returns:
            ID of the newly created derived FOV.

        Raises:
            ExperimentError: If the source FOV does not exist.
        """
        # 1. Get source FOV info
        source = self._db.get_fov(source_fov_id)
        if source is None:
            raise ExperimentError(
                f"Source FOV {uuid_to_str(source_fov_id)} not found"
            )

        # 2. Read source channel arrays
        source_hex = uuid_to_hex(source_fov_id)
        channels = self._db.get_channels(source["experiment_id"])
        channel_arrays: dict[int, np.ndarray] = {}
        for idx in range(len(channels)):
            try:
                channel_arrays[idx] = self._layers.read_image_channel_numpy(
                    source_hex, idx
                )
            except Exception:
                pass  # Channel may not exist in zarr

        # 3. Apply transform
        modified_arrays = transform_fn(channel_arrays)

        # 4. Generate new FOV id and write zarr (OUTSIDE transaction)
        new_fov_id = new_uuid()
        new_hex = uuid_to_hex(new_fov_id)
        zarr_path = self._layers.write_image_channels(new_hex, modified_arrays)

        # 5. Compute lineage fields
        source_depth = source["lineage_depth"] if source["lineage_depth"] else 0
        new_depth = source_depth + 1

        # Build lineage_path: append this FOV's hex to parent's path
        parent_path = source["lineage_path"]
        if parent_path:
            new_lineage_path = f"{parent_path.rstrip('/')}/{new_hex}"
        else:
            # Parent has no path yet — construct from root
            source_hex_id = uuid_to_hex(source_fov_id)
            new_lineage_path = f"/{source_hex_id}/{new_hex}"

        # 6. All DB operations in a single atomic transaction
        with self._db.transaction():
            # Auto-name
            source_name = source["auto_name"]
            auto_name = (
                f"{source_name}_{derivation_op}"
                if source_name
                else derivation_op
            )

            # Insert new FOV with lineage fields and pixel_size_um
            self._db.insert_fov(
                id=new_fov_id,
                experiment_id=source["experiment_id"],
                condition_id=source["condition_id"],
                bio_rep_id=source["bio_rep_id"],
                parent_fov_id=source_fov_id,
                derivation_op=derivation_op,
                derivation_params=json.dumps(params),
                status="pending",
                auto_name=auto_name,
                display_name=display_name,
                zarr_path=zarr_path,
                timepoint_id=source["timepoint_id"],
                pixel_size_um=source["pixel_size_um"],
                pipeline_run_id=pipeline_run_id,
                lineage_depth=new_depth,
                lineage_path=new_lineage_path,
                channel_metadata=channel_metadata,
            )

            # Copy active segmentation assignments
            active = self._db.get_active_assignments(source_fov_id)
            for seg_assign in active["segmentation"]:
                self._db.assign_segmentation(
                    [new_fov_id],
                    seg_assign["segmentation_set_id"],
                    seg_assign["roi_type_id"],
                    seg_assign["pipeline_run_id"],
                    assigned_by="derived_fov",
                )

            # Copy active mask assignments
            for mask_assign in active["mask"]:
                self._db.assign_mask(
                    [new_fov_id],
                    mask_assign["threshold_mask_id"],
                    mask_assign["purpose"],
                    mask_assign["pipeline_run_id"],
                    assigned_by="derived_fov",
                )

            # Duplicate top-level ROIs (cells, NOT sub-cellular) using bulk insert
            # CRITICAL: Preserve existing cell_identity_id references — do NOT
            # create new cell_identities. Cell identities are created ONCE at
            # segmentation and REUSED across derived FOVs.
            cells = self._db.get_cells(source_fov_id)
            if cells:
                roi_tuples = [
                    (
                        new_uuid(),
                        new_fov_id,
                        cell["roi_type_id"],
                        cell["cell_identity_id"],
                        None,  # parent_roi_id
                        cell["label_id"],
                        cell["bbox_y"],
                        cell["bbox_x"],
                        cell["bbox_h"],
                        cell["bbox_w"],
                        cell["area_px"],
                    )
                    for cell in cells
                ]
                self._db.insert_rois_bulk(roi_tuples)

            # Set status to imported (inside transaction for atomicity)
            self._db.set_fov_status(
                new_fov_id, FovStatus.imported, "Derived FOV created"
            )

        return new_fov_id

    # ------------------------------------------------------------------
    # derive_fov: public alias for create_derived_fov
    # ------------------------------------------------------------------

    def derive_fov(
        self,
        source_fov_id: bytes,
        derivation_op: str,
        params: dict,
        transform_fn: Callable[[dict[int, np.ndarray]], dict[int, np.ndarray]],
        *,
        display_name: str | None = None,
        channel_metadata: str | None = None,
        pipeline_run_id: bytes | None = None,
    ) -> bytes:
        """Create a derived FOV (public API).

        Orchestrates the full derived FOV creation: DB insert, Zarr write,
        assignment copy, ROI duplication, and status transition.

        This is the preferred entry point for plugins. It delegates to
        ``create_derived_fov`` which implements the four-step contract.

        Args:
            source_fov_id: ID of the source FOV.
            derivation_op: Name of the operation.
            params: Operation parameters.
            transform_fn: Channel array transform function.
            display_name: Optional user-facing name.
            channel_metadata: Optional JSON channel metadata.
            pipeline_run_id: Optional pipeline run ID.

        Returns:
            ID of the newly created derived FOV.
        """
        return self.create_derived_fov(
            source_fov_id=source_fov_id,
            derivation_op=derivation_op,
            params=params,
            transform_fn=transform_fn,
            display_name=display_name,
            channel_metadata=channel_metadata,
            pipeline_run_id=pipeline_run_id,
        )

    # ------------------------------------------------------------------
    # Lineage tree queries
    # ------------------------------------------------------------------

    def get_fov_tree(self, fov_id: bytes) -> dict:
        """Return the full lineage tree for an FOV.

        Queries both ancestors and descendants to build a complete
        lineage picture.

        Args:
            fov_id: Any FOV in the lineage.

        Returns:
            Dict with ``'fov'`` (the queried FOV row), ``'ancestors'``
            (list of ancestor rows), and ``'descendants'`` (list of
            descendant rows).
        """
        fov = self._db.get_fov(fov_id)
        if fov is None:
            raise ExperimentError(
                f"FOV {uuid_to_str(fov_id)} not found"
            )

        lineage = self._db.get_fov_lineage(fov_id, direction="both")
        return {
            "fov": fov,
            "ancestors": lineage.get("ancestors", []),
            "descendants": lineage.get("descendants", []),
        }

    # ------------------------------------------------------------------
    # Cross-lineage measurement queries
    # ------------------------------------------------------------------

    def get_measurements_across_lineage(
        self, cell_identity_id: bytes
    ) -> list:
        """Return measurements for a cell identity across all derived FOVs.

        Joins measurements -> rois -> cell_identities to find all
        measurements for a single biological entity across the lineage.

        Args:
            cell_identity_id: The cell identity UUID.

        Returns:
            List of measurement rows with fov_id and derivation info.
        """
        return self._db.get_cross_lineage_measurements(cell_identity_id)

    # ------------------------------------------------------------------
    # Soft-delete
    # ------------------------------------------------------------------

    def delete_fov(self, fov_id: bytes) -> None:
        """Soft-delete a FOV: mark deleting, remove zarr, mark deleted.

        Args:
            fov_id: ID of the FOV to delete.
        """
        self._db.set_fov_status(
            fov_id, FovStatus.deleting, "Deletion requested"
        )
        fov = self._db.get_fov(fov_id)
        if fov and fov["zarr_path"]:
            try:
                self._layers.delete_path(fov["zarr_path"])
            except FileNotFoundError:
                pass  # Already deleted
        self._db.set_fov_status(
            fov_id, FovStatus.deleted, "Deletion complete"
        )

    # ------------------------------------------------------------------
    # Lineage: mark descendants stale (delegation)
    # ------------------------------------------------------------------

    def mark_descendants_stale(self, fov_id: bytes) -> int:
        """Mark all descendant FOVs as stale.

        Args:
            fov_id: ID of the ancestor FOV.

        Returns:
            Number of FOVs marked stale.
        """
        return self._db.mark_descendants_stale(fov_id)

    # ------------------------------------------------------------------
    # Measurement dispatch (stub for Gate 2)
    # ------------------------------------------------------------------

    def dispatch_measurements(self, needed: list[MeasurementNeeded]) -> int:
        """Record that measurements are needed.

        Currently a stub: logs what's needed and returns count.
        Plugins must manually call ``measure_fov()`` (from the measure
        module) after creating derived FOVs. Full dispatch wiring is
        planned for Gate 2.

        TODO(gate2): Wire to MeasurementEngine.measure_fov() for
        automatic measurement dispatch on config changes and derived
        FOV creation.

        Args:
            needed: List of MeasurementNeeded items.

        Returns:
            Number of measurement items dispatched.
        """
        for item in needed:
            logger.info(
                "Measurement needed: fov=%s, reason=%s",
                uuid_to_str(item.fov_id),
                item.reason,
            )
        return len(needed)

    # ------------------------------------------------------------------
    # ROI insertion with cell identity enforcement
    # ------------------------------------------------------------------

    def insert_roi_checked(
        self,
        id: bytes,
        fov_id: bytes,
        roi_type_id: bytes,
        cell_identity_id: bytes | None,
        parent_roi_id: bytes | None,
        label_id: int,
        bbox_y: int,
        bbox_x: int,
        bbox_h: int,
        bbox_w: int,
        area_px: int,
    ) -> int:
        """Insert ROI with cell identity enforcement.

        Top-level ROIs (roi_type with parent_type_id IS NULL):
            require non-NULL cell_identity_id.
        Sub-cellular ROIs:
            require NULL cell_identity_id, require non-NULL parent_roi_id.

        Args:
            id: UUID for the new ROI.
            fov_id: FOV the ROI belongs to.
            roi_type_id: ROI type definition ID.
            cell_identity_id: Cell identity ID (required for top-level).
            parent_roi_id: Parent ROI ID (required for sub-cellular).
            label_id: Label integer in the label image.
            bbox_y: Bounding box top-left Y.
            bbox_x: Bounding box top-left X.
            bbox_h: Bounding box height.
            bbox_w: Bounding box width.
            area_px: Area in pixels.

        Returns:
            Row count (1 on success).

        Raises:
            ExperimentError: If cell identity enforcement rules are violated.
        """
        roi_type = self._db.get_roi_type_definition(roi_type_id)
        if roi_type is None:
            raise ExperimentError(
                f"ROI type {uuid_to_str(roi_type_id)} not found"
            )

        is_top_level = roi_type["parent_type_id"] is None

        if is_top_level and cell_identity_id is None:
            raise ExperimentError(
                "Top-level ROIs require a cell_identity_id"
            )
        if not is_top_level and cell_identity_id is not None:
            raise ExperimentError(
                "Sub-cellular ROIs must have NULL cell_identity_id"
            )
        if not is_top_level and parent_roi_id is None:
            raise ExperimentError(
                "Sub-cellular ROIs require a parent_roi_id"
            )

        return self._db.insert_roi(
            id=id,
            fov_id=fov_id,
            roi_type_id=roi_type_id,
            cell_identity_id=cell_identity_id,
            parent_roi_id=parent_roi_id,
            label_id=label_id,
            bbox_y=bbox_y,
            bbox_x=bbox_x,
            bbox_h=bbox_h,
            bbox_w=bbox_w,
            area_px=area_px,
        )

    # ------------------------------------------------------------------
    # CSV Export
    # ------------------------------------------------------------------

    def export_measurements_csv(
        self, fov_ids: list[bytes], output_path: Path
    ) -> int:
        """Basic CSV export using active measurements query.

        Writes CSV with human-readable scope names (SCOPE_DISPLAY mapping).

        Args:
            fov_ids: List of FOV IDs to export measurements for.
            output_path: File path for the output CSV.

        Returns:
            Number of rows written.
        """
        import csv

        from percell4.core.constants import SCOPE_DISPLAY

        rows: list[dict[str, Any]] = []
        for fov_id in fov_ids:
            measurements = self._db.get_active_measurements(fov_id)
            for m in measurements:
                rows.append(
                    {
                        "fov_id": uuid_to_str(m["fov_id"])
                        if "fov_id" in m.keys()
                        else uuid_to_str(fov_id),
                        "roi_id": uuid_to_str(m["roi_id"]),
                        "channel_id": uuid_to_str(m["channel_id"]),
                        "metric": m["metric"],
                        "scope": SCOPE_DISPLAY.get(m["scope"], m["scope"]),
                        "value": m["value"],
                    }
                )

        if rows:
            with open(output_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)

        return len(rows)
