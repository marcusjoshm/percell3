"""ExperimentDB — SQLite CRUD and connection management for PerCell 4.

Provides connection lifecycle (open/close/context manager), SAVEPOINT-based
nested transactions, and typed CRUD methods for all entity tables.

This module sits at the hexagonal boundary: it depends ONLY on the Python
stdlib and percell4.core internals.  No zarr, numpy, or dask imports are
permitted here.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from percell4.core.constants import (
    DEFAULT_BATCH_SIZE,
    ENTITY_TABLES,
    MERGE_TABLE_ORDER,
    VALID_TRANSITIONS,
    FovStatus,
    MAX_LINEAGE_DEPTH,
)
from percell4.core.db_types import new_uuid
from percell4.core.exceptions import InvalidStatusTransition, MergeConflictError
from percell4.core.models import MeasurementNeeded
from percell4.core.schema import SCHEMA_VERSION, _configure_connection, create_schema

logger = logging.getLogger(__name__)

# Type alias for sqlite3.Row (returned from queries)
Row = sqlite3.Row


class ExperimentDB:
    """SQLite database interface for a PerCell 4 experiment.

    Manages connection lifecycle and provides CRUD methods for all entity
    tables.  Transaction nesting is implemented via SAVEPOINTs.

    Usage::

        db = ExperimentDB(Path("experiment.db"))
        with db:
            with db.transaction():
                db.insert_experiment(new_uuid(), "My Experiment")

    Or without the context manager::

        db = ExperimentDB(Path("experiment.db"))
        db.open()
        try:
            with db.transaction():
                db.insert_experiment(new_uuid(), "My Experiment")
        finally:
            db.close()
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._savepoint_counter: int = 0
        self._in_transaction: bool = False

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def open(self) -> None:
        """Open the database connection and create the schema if needed."""
        self._conn = sqlite3.connect(str(self._db_path))
        _configure_connection(self._conn)
        create_schema(self._conn)

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> ExperimentDB:
        self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        self.close()

    @property
    def connection(self) -> sqlite3.Connection:
        """Return the underlying connection, raising if not open."""
        if self._conn is None:
            raise RuntimeError("ExperimentDB is not open")
        return self._conn

    # ------------------------------------------------------------------
    # Transaction management with SAVEPOINT nesting
    # ------------------------------------------------------------------

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Transaction context manager with SAVEPOINT nesting.

        First call uses BEGIN IMMEDIATE / COMMIT / ROLLBACK.
        Nested calls use SAVEPOINT sp_N / RELEASE / ROLLBACK TO.
        """
        conn = self.connection

        if not self._in_transaction:
            # Outermost transaction
            self._in_transaction = True
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            finally:
                self._in_transaction = False
        else:
            # Nested transaction via SAVEPOINT
            self._savepoint_counter += 1
            sp_name = f"sp_{self._savepoint_counter}"
            conn.execute(f"SAVEPOINT {sp_name}")
            try:
                yield
                conn.execute(f"RELEASE {sp_name}")
            except BaseException:
                conn.execute(f"ROLLBACK TO {sp_name}")
                raise

    # ------------------------------------------------------------------
    # Experiments
    # ------------------------------------------------------------------

    def insert_experiment(
        self,
        id: bytes,
        name: str,
        schema_version: str = SCHEMA_VERSION,
        config_hash: str | None = None,
    ) -> int:
        """Insert an experiment record. Returns rowcount."""
        cur = self.connection.execute(
            "INSERT INTO experiments (id, name, schema_version, config_hash) "
            "VALUES (?, ?, ?, ?)",
            (id, name, schema_version, config_hash),
        )
        return cur.rowcount

    def get_experiment(self) -> Row | None:
        """Return the first experiment record (single-experiment DB)."""
        return self.connection.execute(
            "SELECT * FROM experiments LIMIT 1"
        ).fetchone()

    # ------------------------------------------------------------------
    # Conditions
    # ------------------------------------------------------------------

    def insert_condition(
        self, id: bytes, experiment_id: bytes, name: str
    ) -> int:
        """Insert a condition record. Returns rowcount."""
        cur = self.connection.execute(
            "INSERT INTO conditions (id, experiment_id, name) "
            "VALUES (?, ?, ?)",
            (id, experiment_id, name),
        )
        return cur.rowcount

    def get_conditions(self, experiment_id: bytes) -> list[Row]:
        """Return all conditions for an experiment."""
        return self.connection.execute(
            "SELECT * FROM conditions WHERE experiment_id = ?",
            (experiment_id,),
        ).fetchall()

    def get_condition(self, id: bytes) -> Row | None:
        """Return a single condition by ID."""
        return self.connection.execute(
            "SELECT * FROM conditions WHERE id = ?", (id,)
        ).fetchone()

    # ------------------------------------------------------------------
    # Bio Reps
    # ------------------------------------------------------------------

    def insert_bio_rep(
        self, id: bytes, experiment_id: bytes, condition_id: bytes, name: str
    ) -> int:
        """Insert a biological replicate record. Returns rowcount."""
        cur = self.connection.execute(
            "INSERT INTO bio_reps (id, experiment_id, condition_id, name) "
            "VALUES (?, ?, ?, ?)",
            (id, experiment_id, condition_id, name),
        )
        return cur.rowcount

    def get_bio_reps(self, experiment_id: bytes) -> list[Row]:
        """Return all bio reps for an experiment."""
        return self.connection.execute(
            "SELECT * FROM bio_reps WHERE experiment_id = ?",
            (experiment_id,),
        ).fetchall()

    def get_bio_rep(self, id: bytes) -> Row | None:
        """Return a single bio rep by ID."""
        return self.connection.execute(
            "SELECT * FROM bio_reps WHERE id = ?", (id,)
        ).fetchone()

    # ------------------------------------------------------------------
    # Channels
    # ------------------------------------------------------------------

    def insert_channel(
        self,
        id: bytes,
        experiment_id: bytes,
        name: str,
        role: str | None = None,
        color: str | None = None,
        display_order: int = 0,
    ) -> int:
        """Insert a channel record. Returns rowcount."""
        cur = self.connection.execute(
            "INSERT INTO channels "
            "(id, experiment_id, name, role, color, display_order) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (id, experiment_id, name, role, color, display_order),
        )
        return cur.rowcount

    def get_channels(self, experiment_id: bytes) -> list[Row]:
        """Return all channels for an experiment."""
        return self.connection.execute(
            "SELECT * FROM channels WHERE experiment_id = ? "
            "ORDER BY display_order",
            (experiment_id,),
        ).fetchall()

    def get_channel(self, id: bytes) -> Row | None:
        """Return a single channel by ID."""
        return self.connection.execute(
            "SELECT * FROM channels WHERE id = ?", (id,)
        ).fetchone()

    # ------------------------------------------------------------------
    # Timepoints
    # ------------------------------------------------------------------

    def insert_timepoint(
        self,
        id: bytes,
        experiment_id: bytes,
        name: str,
        time_seconds: float | None = None,
        display_order: int = 0,
    ) -> int:
        """Insert a timepoint record. Returns rowcount."""
        cur = self.connection.execute(
            "INSERT INTO timepoints "
            "(id, experiment_id, name, time_seconds, display_order) "
            "VALUES (?, ?, ?, ?, ?)",
            (id, experiment_id, name, time_seconds, display_order),
        )
        return cur.rowcount

    def get_timepoints(self, experiment_id: bytes) -> list[Row]:
        """Return all timepoints for an experiment, ordered by display_order."""
        return self.connection.execute(
            "SELECT * FROM timepoints WHERE experiment_id = ? "
            "ORDER BY display_order",
            (experiment_id,),
        ).fetchall()

    # ------------------------------------------------------------------
    # FOVs
    # ------------------------------------------------------------------

    def insert_fov(
        self,
        id: bytes,
        experiment_id: bytes,
        condition_id: bytes | None = None,
        bio_rep_id: bytes | None = None,
        parent_fov_id: bytes | None = None,
        derivation_op: str | None = None,
        derivation_params: str | None = None,
        status: str = "pending",
        auto_name: str | None = None,
        zarr_path: str | None = None,
        timepoint_id: bytes | None = None,
        pixel_size_um: float | None = None,
    ) -> int:
        """Insert an FOV record. Returns rowcount."""
        cur = self.connection.execute(
            "INSERT INTO fovs "
            "(id, experiment_id, condition_id, bio_rep_id, parent_fov_id, "
            " derivation_op, derivation_params, status, auto_name, "
            " zarr_path, timepoint_id, pixel_size_um) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                id, experiment_id, condition_id, bio_rep_id, parent_fov_id,
                derivation_op, derivation_params, status, auto_name,
                zarr_path, timepoint_id, pixel_size_um,
            ),
        )
        return cur.rowcount

    def get_fov(self, id: bytes) -> Row | None:
        """Return a single FOV by ID."""
        return self.connection.execute(
            "SELECT * FROM fovs WHERE id = ?", (id,)
        ).fetchone()

    def get_fovs(self, experiment_id: bytes) -> list[Row]:
        """Return all FOVs for an experiment."""
        return self.connection.execute(
            "SELECT * FROM fovs WHERE experiment_id = ?",
            (experiment_id,),
        ).fetchall()

    def get_fovs_by_status(
        self, experiment_id: bytes, status: str
    ) -> list[Row]:
        """Return FOVs filtered by status."""
        return self.connection.execute(
            "SELECT * FROM fovs WHERE experiment_id = ? AND status = ?",
            (experiment_id, status),
        ).fetchall()

    # ------------------------------------------------------------------
    # ROI Type Definitions
    # ------------------------------------------------------------------

    def insert_roi_type_definition(
        self,
        id: bytes,
        experiment_id: bytes,
        name: str,
        parent_type_id: bytes | None = None,
    ) -> int:
        """Insert an ROI type definition. Returns rowcount."""
        cur = self.connection.execute(
            "INSERT INTO roi_type_definitions "
            "(id, experiment_id, name, parent_type_id) "
            "VALUES (?, ?, ?, ?)",
            (id, experiment_id, name, parent_type_id),
        )
        return cur.rowcount

    def get_roi_type_definitions(self, experiment_id: bytes) -> list[Row]:
        """Return all ROI type definitions for an experiment."""
        return self.connection.execute(
            "SELECT * FROM roi_type_definitions WHERE experiment_id = ?",
            (experiment_id,),
        ).fetchall()

    def get_roi_type_definition(self, id: bytes) -> Row | None:
        """Return a single ROI type definition by ID."""
        return self.connection.execute(
            "SELECT * FROM roi_type_definitions WHERE id = ?", (id,)
        ).fetchone()

    # ------------------------------------------------------------------
    # Cell Identities
    # ------------------------------------------------------------------

    def insert_cell_identity(
        self, id: bytes, origin_fov_id: bytes, roi_type_id: bytes
    ) -> int:
        """Insert a cell identity record. Returns rowcount."""
        cur = self.connection.execute(
            "INSERT INTO cell_identities (id, origin_fov_id, roi_type_id) "
            "VALUES (?, ?, ?)",
            (id, origin_fov_id, roi_type_id),
        )
        return cur.rowcount

    def get_cell_identity(self, id: bytes) -> Row | None:
        """Return a single cell identity by ID."""
        return self.connection.execute(
            "SELECT * FROM cell_identities WHERE id = ?", (id,)
        ).fetchone()

    # ------------------------------------------------------------------
    # ROIs
    # ------------------------------------------------------------------

    def insert_roi(
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
        """Insert an ROI record. Returns rowcount."""
        cur = self.connection.execute(
            "INSERT INTO rois "
            "(id, fov_id, roi_type_id, cell_identity_id, parent_roi_id, "
            " label_id, bbox_y, bbox_x, bbox_h, bbox_w, area_px) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                id, fov_id, roi_type_id, cell_identity_id, parent_roi_id,
                label_id, bbox_y, bbox_x, bbox_h, bbox_w, area_px,
            ),
        )
        return cur.rowcount

    def get_rois(self, fov_id: bytes) -> list[Row]:
        """Return all ROIs for an FOV."""
        return self.connection.execute(
            "SELECT * FROM rois WHERE fov_id = ?", (fov_id,)
        ).fetchall()

    def get_rois_by_fov_and_type(
        self, fov_id: bytes, roi_type_id: bytes
    ) -> list[Row]:
        """Return ROIs filtered by FOV and ROI type ID."""
        return self.connection.execute(
            "SELECT * FROM rois WHERE fov_id = ? AND roi_type_id = ?",
            (fov_id, roi_type_id),
        ).fetchall()

    # ------------------------------------------------------------------
    # Segmentation Sets
    # ------------------------------------------------------------------

    def insert_segmentation_set(
        self,
        id: bytes,
        experiment_id: bytes,
        produces_roi_type_id: bytes,
        seg_type: str,
        op_config_name: str | None = None,
        source_channel: str | None = None,
        model_name: str | None = None,
        parameters: str | None = None,
        fov_count: int = 0,
        total_roi_count: int = 0,
    ) -> int:
        """Insert a segmentation set record. Returns rowcount."""
        cur = self.connection.execute(
            "INSERT INTO segmentation_sets "
            "(id, experiment_id, produces_roi_type_id, seg_type, "
            " op_config_name, source_channel, model_name, parameters, "
            " fov_count, total_roi_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                id, experiment_id, produces_roi_type_id, seg_type,
                op_config_name, source_channel, model_name, parameters,
                fov_count, total_roi_count,
            ),
        )
        return cur.rowcount

    def get_segmentation_set(self, id: bytes) -> Row | None:
        """Return a single segmentation set by ID."""
        return self.connection.execute(
            "SELECT * FROM segmentation_sets WHERE id = ?", (id,)
        ).fetchone()

    # ------------------------------------------------------------------
    # Threshold Masks
    # ------------------------------------------------------------------

    def insert_threshold_mask(
        self,
        id: bytes,
        fov_id: bytes,
        source_channel: str,
        grouping_channel: str | None = None,
        method: str = "otsu",
        threshold_value: float = 0.0,
        histogram: str | None = None,
        zarr_path: str | None = None,
        status: str = "pending",
    ) -> int:
        """Insert a threshold mask record. Returns rowcount."""
        cur = self.connection.execute(
            "INSERT INTO threshold_masks "
            "(id, fov_id, source_channel, grouping_channel, method, "
            " threshold_value, histogram, zarr_path, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                id, fov_id, source_channel, grouping_channel, method,
                threshold_value, histogram, zarr_path, status,
            ),
        )
        return cur.rowcount

    def get_threshold_masks(self, fov_id: bytes) -> list[Row]:
        """Return all threshold masks for an FOV."""
        return self.connection.execute(
            "SELECT * FROM threshold_masks WHERE fov_id = ?", (fov_id,)
        ).fetchall()

    # ------------------------------------------------------------------
    # Pipeline Runs
    # ------------------------------------------------------------------

    def insert_pipeline_run(
        self,
        id: bytes,
        operation_name: str,
        config_snapshot: str | None = None,
    ) -> int:
        """Insert a pipeline run record (status defaults to 'running').

        Returns rowcount.
        """
        cur = self.connection.execute(
            "INSERT INTO pipeline_runs (id, operation_name, config_snapshot) "
            "VALUES (?, ?, ?)",
            (id, operation_name, config_snapshot),
        )
        return cur.rowcount

    def complete_pipeline_run(
        self,
        id: bytes,
        status: str = "completed",
        error_message: str | None = None,
    ) -> int:
        """Mark a pipeline run as completed or failed. Returns rowcount."""
        cur = self.connection.execute(
            "UPDATE pipeline_runs "
            "SET status = ?, completed_at = datetime('now'), "
            "    error_message = ? "
            "WHERE id = ?",
            (status, error_message, id),
        )
        return cur.rowcount

    # ------------------------------------------------------------------
    # Measurements
    # ------------------------------------------------------------------

    def insert_measurement(
        self,
        id: bytes,
        roi_id: bytes,
        channel_id: bytes,
        metric: str,
        scope: str,
        value: float,
        pipeline_run_id: bytes,
    ) -> int:
        """Insert a single measurement record. Returns rowcount."""
        cur = self.connection.execute(
            "INSERT INTO measurements "
            "(id, roi_id, channel_id, metric, scope, value, pipeline_run_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (id, roi_id, channel_id, metric, scope, value, pipeline_run_id),
        )
        return cur.rowcount

    def add_measurements_bulk(self, measurements: list[tuple]) -> int:
        """Insert multiple measurements via executemany.

        Each tuple: (id, roi_id, channel_id, metric, scope, value,
        pipeline_run_id).

        Returns the number of rows inserted.
        """
        cur = self.connection.executemany(
            "INSERT INTO measurements "
            "(id, roi_id, channel_id, metric, scope, value, pipeline_run_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            measurements,
        )
        return cur.rowcount

    # ------------------------------------------------------------------
    # Intensity Groups
    # ------------------------------------------------------------------

    def insert_intensity_group(
        self,
        id: bytes,
        experiment_id: bytes,
        name: str,
        channel_id: bytes,
        pipeline_run_id: bytes,
        group_index: int | None = None,
        lower_bound: float | None = None,
        upper_bound: float | None = None,
        color_hex: str | None = None,
    ) -> int:
        """Insert an intensity group record. Returns rowcount."""
        cur = self.connection.execute(
            "INSERT INTO intensity_groups "
            "(id, experiment_id, name, channel_id, pipeline_run_id, "
            " group_index, lower_bound, upper_bound, color_hex) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                id, experiment_id, name, channel_id, pipeline_run_id,
                group_index, lower_bound, upper_bound, color_hex,
            ),
        )
        return cur.rowcount

    def get_intensity_groups(self, experiment_id: bytes) -> list[Row]:
        """Return all intensity groups for an experiment."""
        return self.connection.execute(
            "SELECT * FROM intensity_groups WHERE experiment_id = ?",
            (experiment_id,),
        ).fetchall()

    # ------------------------------------------------------------------
    # Cell Group Assignments
    # ------------------------------------------------------------------

    def insert_cell_group_assignment(
        self,
        id: bytes,
        intensity_group_id: bytes,
        roi_id: bytes,
        pipeline_run_id: bytes,
    ) -> int:
        """Insert a cell group assignment record. Returns rowcount."""
        cur = self.connection.execute(
            "INSERT INTO cell_group_assignments "
            "(id, intensity_group_id, roi_id, pipeline_run_id) "
            "VALUES (?, ?, ?, ?)",
            (id, intensity_group_id, roi_id, pipeline_run_id),
        )
        return cur.rowcount

    # ------------------------------------------------------------------
    # Convenience queries
    # ------------------------------------------------------------------

    def get_cells(self, fov_id: bytes) -> list[Row]:
        """Return ROIs whose roi_type is a top-level type (parent_type_id IS NULL).

        This filters to "cell"-level ROIs by joining to roi_type_definitions
        and checking that the type has no parent.
        """
        return self.connection.execute(
            "SELECT r.* FROM rois r "
            "JOIN roi_type_definitions rtd ON r.roi_type_id = rtd.id "
            "WHERE r.fov_id = ? AND rtd.parent_type_id IS NULL",
            (fov_id,),
        ).fetchall()

    def get_rois_by_type(
        self, fov_id: bytes, roi_type_name: str
    ) -> list[Row]:
        """Return ROIs filtered by FOV and ROI type name (via JOIN)."""
        return self.connection.execute(
            "SELECT r.* FROM rois r "
            "JOIN roi_type_definitions rtd ON r.roi_type_id = rtd.id "
            "WHERE r.fov_id = ? AND rtd.name = ?",
            (fov_id, roi_type_name),
        ).fetchall()

    # ------------------------------------------------------------------
    # Batch safety helper
    # ------------------------------------------------------------------

    def _batch_in_query(
        self,
        query_template: str,
        params_before: tuple,
        ids: list[bytes],
        params_after: tuple = (),
    ) -> list[Row]:
        """Execute a query with an IN clause, chunking to avoid the 999-param limit.

        Args:
            query_template: SQL with a ``{placeholders}`` marker where the
                IN clause values go. Example:
                ``"SELECT * FROM rois WHERE id IN ({placeholders})"``
            params_before: Parameters to bind before the IN values.
            ids: The list of IDs for the IN clause.
            params_after: Parameters to bind after the IN values.

        Returns:
            Combined list of rows from all batches.
        """
        results: list[Row] = []
        for i in range(0, len(ids), DEFAULT_BATCH_SIZE):
            batch = ids[i : i + DEFAULT_BATCH_SIZE]
            placeholders = ", ".join("?" * len(batch))
            sql = query_template.format(placeholders=placeholders)
            params = params_before + tuple(batch) + params_after
            results.extend(self.connection.execute(sql, params).fetchall())
        return results

    # ------------------------------------------------------------------
    # Assignments
    # ------------------------------------------------------------------

    def assign_segmentation(
        self,
        fov_ids: list[bytes],
        seg_set_id: bytes,
        roi_type_id: bytes,
        pipeline_run_id: bytes,
        assigned_by: str | None = None,
    ) -> list[MeasurementNeeded]:
        """Assign a segmentation set to one or more FOVs.

        For each FOV, deactivates any existing active assignment for the
        same (fov_id, roi_type_id) pair and creates a new active one.

        Returns a list of MeasurementNeeded items indicating what needs
        to be (re-)measured.
        """
        conn = self.connection

        # Get all channel IDs for the experiment once
        channel_rows = conn.execute(
            "SELECT id FROM channels WHERE experiment_id = "
            "(SELECT experiment_id FROM fovs WHERE id = ? LIMIT 1)",
            (fov_ids[0],),
        ).fetchall()
        channel_ids = [r["id"] for r in channel_rows]

        results: list[MeasurementNeeded] = []
        for fov_id in fov_ids:
            # Check for existing active assignment
            existing = conn.execute(
                "SELECT id FROM fov_segmentation_assignments "
                "WHERE fov_id = ? AND roi_type_id = ? AND is_active = 1",
                (fov_id, roi_type_id),
            ).fetchone()

            if existing is not None:
                # Deactivate old assignment
                conn.execute(
                    "UPDATE fov_segmentation_assignments "
                    "SET is_active = 0, deactivated_at = datetime('now') "
                    "WHERE fov_id = ? AND roi_type_id = ? AND is_active = 1",
                    (fov_id, roi_type_id),
                )
                reason: str = "reassignment"
            else:
                reason = "new_assignment"

            # Insert new active assignment
            conn.execute(
                "INSERT INTO fov_segmentation_assignments "
                "(id, fov_id, segmentation_set_id, roi_type_id, is_active, "
                " pipeline_run_id, assigned_by) "
                "VALUES (?, ?, ?, ?, 1, ?, ?)",
                (new_uuid(), fov_id, seg_set_id, roi_type_id,
                 pipeline_run_id, assigned_by),
            )

            results.append(MeasurementNeeded(
                fov_id=fov_id,
                roi_type_id=roi_type_id,
                channel_ids=channel_ids,
                reason=reason,
            ))

        return results

    def assign_mask(
        self,
        fov_ids: list[bytes],
        threshold_mask_id: bytes,
        purpose: str,
        pipeline_run_id: bytes,
        assigned_by: str | None = None,
    ) -> list[MeasurementNeeded]:
        """Assign a threshold mask to one or more FOVs.

        For each FOV, deactivates any existing active assignment for the
        same (fov_id, threshold_mask_id, purpose) triple and creates a
        new active one.

        Returns MeasurementNeeded items only when purpose is
        'measurement_scope'.
        """
        conn = self.connection

        # Get channel IDs once (needed for MeasurementNeeded if applicable)
        channel_ids: list[bytes] = []
        if purpose == "measurement_scope":
            channel_rows = conn.execute(
                "SELECT id FROM channels WHERE experiment_id = "
                "(SELECT experiment_id FROM fovs WHERE id = ? LIMIT 1)",
                (fov_ids[0],),
            ).fetchall()
            channel_ids = [r["id"] for r in channel_rows]

        results: list[MeasurementNeeded] = []
        for fov_id in fov_ids:
            # Check for existing active assignment
            existing = conn.execute(
                "SELECT id FROM fov_mask_assignments "
                "WHERE fov_id = ? AND threshold_mask_id = ? "
                "AND purpose = ? AND is_active = 1",
                (fov_id, threshold_mask_id, purpose),
            ).fetchone()

            if existing is not None:
                conn.execute(
                    "UPDATE fov_mask_assignments "
                    "SET is_active = 0, deactivated_at = datetime('now') "
                    "WHERE fov_id = ? AND threshold_mask_id = ? "
                    "AND purpose = ? AND is_active = 1",
                    (fov_id, threshold_mask_id, purpose),
                )
                reason: str = "reassignment"
            else:
                reason = "new_assignment"

            conn.execute(
                "INSERT INTO fov_mask_assignments "
                "(id, fov_id, threshold_mask_id, purpose, is_active, "
                " pipeline_run_id, assigned_by) "
                "VALUES (?, ?, ?, ?, 1, ?, ?)",
                (new_uuid(), fov_id, threshold_mask_id, purpose,
                 pipeline_run_id, assigned_by),
            )

            if purpose == "measurement_scope":
                # Need roi_type_id — get from active segmentation assignment
                seg_row = conn.execute(
                    "SELECT roi_type_id FROM fov_segmentation_assignments "
                    "WHERE fov_id = ? AND is_active = 1 LIMIT 1",
                    (fov_id,),
                ).fetchone()
                roi_type_id = seg_row["roi_type_id"] if seg_row else b"\x00" * 16
                results.append(MeasurementNeeded(
                    fov_id=fov_id,
                    roi_type_id=roi_type_id,
                    channel_ids=channel_ids,
                    reason=reason,
                ))

        return results

    def get_active_assignments(self, fov_id: bytes) -> dict[str, list[Row]]:
        """Return all active assignments (segmentation and mask) for an FOV.

        Returns:
            Dict with keys ``"segmentation"`` and ``"mask"``, each
            containing a list of active assignment rows.
        """
        conn = self.connection
        seg_rows = conn.execute(
            "SELECT * FROM fov_segmentation_assignments "
            "WHERE fov_id = ? AND is_active = 1",
            (fov_id,),
        ).fetchall()
        mask_rows = conn.execute(
            "SELECT * FROM fov_mask_assignments "
            "WHERE fov_id = ? AND is_active = 1",
            (fov_id,),
        ).fetchall()
        return {"segmentation": seg_rows, "mask": mask_rows}

    def deactivate_assignment(self, table: str, assignment_id: bytes) -> int:
        """Deactivate a single assignment by ID.

        Args:
            table: Must be ``'fov_segmentation_assignments'`` or
                ``'fov_mask_assignments'``.
            assignment_id: The UUID of the assignment row.

        Returns:
            Number of rows updated (0 or 1).

        Raises:
            ValueError: If *table* is not an allowed assignment table.
        """
        allowed = ("fov_segmentation_assignments", "fov_mask_assignments")
        if table not in allowed:
            raise ValueError(
                f"table must be one of {allowed}, got {table!r}"
            )
        cur = self.connection.execute(
            f"UPDATE {table} SET is_active = 0, "
            "deactivated_at = datetime('now') WHERE id = ?",
            (assignment_id,),
        )
        return cur.rowcount

    # ------------------------------------------------------------------
    # FOV Status Machine
    # ------------------------------------------------------------------

    def get_fov_status(self, fov_id: bytes) -> str:
        """Return the current status of an FOV.

        Raises:
            ValueError: If the FOV does not exist.
        """
        row = self.connection.execute(
            "SELECT status FROM fovs WHERE id = ?", (fov_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"FOV not found: {fov_id!r}")
        return row["status"]

    def set_fov_status(
        self,
        fov_id: bytes,
        new_status: str,
        message: str | None = None,
    ) -> None:
        """Transition an FOV to a new status, validating the state machine.

        Raises:
            InvalidStatusTransition: If the transition is not allowed.
        """
        conn = self.connection
        current_status = self.get_fov_status(fov_id)

        # Validate transition
        allowed = VALID_TRANSITIONS.get(FovStatus(current_status), set())
        if new_status not in {s.value for s in allowed}:
            raise InvalidStatusTransition(
                f"Cannot transition from '{current_status}' to '{new_status}'"
            )

        conn.execute(
            "UPDATE fovs SET status = ? WHERE id = ?",
            (new_status, fov_id),
        )
        conn.execute(
            "INSERT INTO fov_status_log (fov_id, old_status, new_status, message) "
            "VALUES (?, ?, ?, ?)",
            (fov_id, current_status, new_status, message),
        )

    def mark_descendants_stale(self, fov_id: bytes) -> int:
        """Mark all descendant FOVs as stale using a recursive CTE.

        Skips FOVs with status 'deleted', 'deleting', or 'pending'.

        Returns:
            Number of FOVs marked stale.
        """
        conn = self.connection
        # First, collect descendant IDs eligible for stale marking
        rows = conn.execute(
            """
            WITH RECURSIVE lineage(id, depth) AS (
                SELECT id, 1 FROM fovs WHERE parent_fov_id = ?
                UNION ALL
                SELECT f.id, l.depth + 1
                FROM fovs f JOIN lineage l ON f.parent_fov_id = l.id
                WHERE l.depth < ?
            )
            SELECT l.id FROM lineage l
            JOIN fovs f ON f.id = l.id
            WHERE f.status NOT IN ('deleted', 'deleting', 'pending')
            """,
            (fov_id, MAX_LINEAGE_DEPTH),
        ).fetchall()

        if not rows:
            return 0

        ids_to_update = [r["id"] for r in rows]
        placeholders = ", ".join("?" * len(ids_to_update))
        cur = conn.execute(
            f"UPDATE fovs SET status = 'stale' "
            f"WHERE id IN ({placeholders})",
            ids_to_update,
        )
        return cur.rowcount

    # ------------------------------------------------------------------
    # Lineage Queries
    # ------------------------------------------------------------------

    def get_descendants(self, fov_id: bytes) -> list[Row]:
        """Return all descendant FOV rows with depth via recursive CTE.

        Depth guard: stops at MAX_LINEAGE_DEPTH levels.
        """
        return self.connection.execute(
            """
            WITH RECURSIVE lineage(id, depth) AS (
                SELECT id, 1 FROM fovs WHERE parent_fov_id = ?
                UNION ALL
                SELECT f.id, l.depth + 1
                FROM fovs f JOIN lineage l ON f.parent_fov_id = l.id
                WHERE l.depth < ?
            )
            SELECT f.*, l.depth
            FROM lineage l JOIN fovs f ON f.id = l.id
            ORDER BY l.depth
            """,
            (fov_id, MAX_LINEAGE_DEPTH),
        ).fetchall()

    def get_ancestors(self, fov_id: bytes) -> list[Row]:
        """Return all ancestor FOV rows with depth via recursive CTE.

        Walks parent_fov_id upward. Depth guard at MAX_LINEAGE_DEPTH.
        """
        return self.connection.execute(
            """
            WITH RECURSIVE lineage(id, depth) AS (
                SELECT parent_fov_id, 1
                FROM fovs WHERE id = ? AND parent_fov_id IS NOT NULL
                UNION ALL
                SELECT f.parent_fov_id, l.depth + 1
                FROM fovs f JOIN lineage l ON f.id = l.id
                WHERE f.parent_fov_id IS NOT NULL AND l.depth < ?
            )
            SELECT f.*, l.depth
            FROM lineage l JOIN fovs f ON f.id = l.id
            ORDER BY l.depth
            """,
            (fov_id, MAX_LINEAGE_DEPTH),
        ).fetchall()

    def check_no_cycle(
        self, fov_id: bytes, proposed_parent_id: bytes
    ) -> bool:
        """Check whether setting fov_id's parent to proposed_parent_id
        would create a cycle.

        Returns True if the assignment is safe (no cycle), False otherwise.
        """
        if fov_id == proposed_parent_id:
            return False

        # Walk ancestors of proposed_parent_id
        ancestors = self.get_ancestors(proposed_parent_id)
        for ancestor in ancestors:
            if ancestor["id"] == fov_id:
                return False
        return True

    # ------------------------------------------------------------------
    # Canonical Active Measurements Query
    # ------------------------------------------------------------------

    def get_active_measurements(self, fov_id: bytes) -> list[Row]:
        """Return measurements filtered through active segmentation assignments.

        This is THE canonical query for exports — it joins measurements to
        ROIs to active assignments, ensuring only measurements from the
        currently active pipeline run are returned.
        """
        return self.connection.execute(
            """
            SELECT m.* FROM measurements m
            JOIN rois r ON m.roi_id = r.id
            JOIN fov_segmentation_assignments fsa
                ON fsa.fov_id = r.fov_id
                AND fsa.roi_type_id = r.roi_type_id
                AND fsa.is_active = 1
            WHERE r.fov_id = ?
                AND m.pipeline_run_id = fsa.pipeline_run_id
            """,
            (fov_id,),
        ).fetchall()

    def get_active_measurements_pivot(
        self, fov_ids: list[bytes]
    ) -> list[Row]:
        """Return active measurements in pivot form (one row per ROI).

        Uses the same active assignment filter as get_active_measurements,
        but produces one row per ROI with columns for each
        channel x metric x scope combination.

        Uses _batch_in_query for safe chunking.
        """
        return self._batch_in_query(
            """
            SELECT m.roi_id,
                   r.label_id,
                   r.fov_id,
                   m.channel_id,
                   m.metric,
                   m.scope,
                   m.value,
                   m.pipeline_run_id
            FROM measurements m
            JOIN rois r ON m.roi_id = r.id
            JOIN fov_segmentation_assignments fsa
                ON fsa.fov_id = r.fov_id
                AND fsa.roi_type_id = r.roi_type_id
                AND fsa.is_active = 1
            WHERE r.fov_id IN ({placeholders})
                AND m.pipeline_run_id = fsa.pipeline_run_id
            ORDER BY r.fov_id, r.label_id, m.channel_id, m.metric, m.scope
            """,
            (),
            fov_ids,
        )

    # ------------------------------------------------------------------
    # Database Merge
    # ------------------------------------------------------------------

    # Statuses excluded from merge — FOVs that are incomplete or being removed
    _EXCLUDED_STATUSES: tuple[str, ...] = (
        "pending", "deleting", "deleted", "error",
    )

    def merge_experiment(self, source_path: Path) -> dict[str, Any]:
        """Merge another .percell database into this one.

        Uses ATTACH DATABASE with parameter binding (no f-string for path),
        INSERT OR IGNORE for BLOB(16) PK tables, and special handling for
        the INTEGER PK ``fov_status_log`` table.

        Returns:
            Dict with merge statistics: table counts, conflicts, warnings,
            and foreign-key violations.
        """
        conn = self.connection
        counts: dict[str, int] = {}
        conflicts: list[str] = []
        warnings: list[str] = []
        fk_violations: list[tuple] = []

        try:
            # ---- Step 1: ATTACH and schema version check ---------------
            conn.execute("ATTACH ? AS source", (str(source_path),))

            target_row = conn.execute(
                "SELECT schema_version FROM experiments"
            ).fetchone()
            source_row = conn.execute(
                "SELECT schema_version FROM source.experiments"
            ).fetchone()

            if target_row is None or source_row is None:
                raise MergeConflictError(
                    "Cannot merge: one or both databases have no experiment record"
                )

            target_ver = target_row["schema_version"]
            source_ver = source_row["schema_version"]
            if target_ver != source_ver:
                raise MergeConflictError(
                    f"Schema version mismatch: target={target_ver}, "
                    f"source={source_ver}"
                )

            # ---- Step 2: Disable foreign keys --------------------------
            conn.execute("PRAGMA foreign_keys = OFF")

            # ---- Step 3: Pre-merge conflict check ----------------------
            for table in ENTITY_TABLES:
                assert table.isidentifier(), f"Bad table name: {table!r}"
                # fov_status_log has INTEGER PK — skip collision check
                if table == "fov_status_log":
                    continue

                # Find rows with same UUID PK but different content
                # Get column names from table info
                col_info = conn.execute(
                    f"PRAGMA table_info({table})"
                ).fetchall()
                col_names = [c["name"] for c in col_info]
                non_pk_cols = [c for c in col_names if c != "id"]

                if not non_pk_cols:
                    continue  # table with only PK has no conflict possible

                # Build comparison conditions for non-PK columns
                # Use IS NOT to handle NULLs correctly
                diff_conditions = " OR ".join(
                    f"main.{table}.{col} IS NOT source.{table}.{col}"
                    for col in non_pk_cols
                )
                sql = (
                    f"SELECT uuid_str(main.{table}.id) AS conflict_id "
                    f"FROM main.{table} "
                    f"JOIN source.{table} "
                    f"ON main.{table}.id = source.{table}.id "
                    f"WHERE {diff_conditions}"
                )
                conflict_rows = conn.execute(sql).fetchall()
                for row in conflict_rows:
                    conflicts.append(
                        f"{table}: UUID {row['conflict_id']} has "
                        f"differing content between source and target"
                    )

            # ---- Step 4: Filter source FOVs (exclude non-committed) ----
            excluded_placeholders = ", ".join(
                "?" * len(self._EXCLUDED_STATUSES)
            )
            conn.execute(
                "CREATE TEMP TABLE _merge_eligible_fovs (id BLOB(16))"
            )
            conn.execute(
                f"INSERT INTO _merge_eligible_fovs "
                f"SELECT id FROM source.fovs "
                f"WHERE status NOT IN ({excluded_placeholders})",
                self._EXCLUDED_STATUSES,
            )

            # ---- Step 5: Insert in MERGE_TABLE_ORDER -------------------
            for table in MERGE_TABLE_ORDER:
                assert table.isidentifier(), f"Bad table name: {table!r}"

                if table == "fovs":
                    sql = (
                        f"INSERT OR IGNORE INTO main.{table} "
                        f"SELECT * FROM source.{table} "
                        f"WHERE status NOT IN ({excluded_placeholders})"
                    )
                    cursor = conn.execute(sql, self._EXCLUDED_STATUSES)
                else:
                    sql = (
                        f"INSERT OR IGNORE INTO main.{table} "
                        f"SELECT * FROM source.{table}"
                    )
                    cursor = conn.execute(sql)
                counts[table] = cursor.rowcount

            # ---- Step 6: Handle fov_status_log (INTEGER PK) -----------
            cursor = conn.execute(
                "INSERT INTO main.fov_status_log "
                "(fov_id, old_status, new_status, message, created_at) "
                "SELECT fov_id, old_status, new_status, message, created_at "
                "FROM source.fov_status_log "
                "WHERE fov_id IN (SELECT id FROM _merge_eligible_fovs)"
            )
            counts["fov_status_log"] = cursor.rowcount

            # ---- Step 7: Post-merge assignment conflict detection ------
            # Check for duplicate active segmentation assignments
            dup_seg_rows = conn.execute(
                "SELECT fov_id, roi_type_id, COUNT(*) as cnt "
                "FROM fov_segmentation_assignments "
                "WHERE is_active = 1 "
                "GROUP BY fov_id, roi_type_id "
                "HAVING cnt > 1"
            ).fetchall()

            for row in dup_seg_rows:
                # Find all active assignments for this pair, deactivate older
                actives = conn.execute(
                    "SELECT id, assigned_at FROM fov_segmentation_assignments "
                    "WHERE fov_id = ? AND roi_type_id = ? AND is_active = 1 "
                    "ORDER BY assigned_at ASC",
                    (row["fov_id"], row["roi_type_id"]),
                ).fetchall()
                # Deactivate all but the most recent (last in ASC order)
                for a in actives[:-1]:
                    conn.execute(
                        "UPDATE fov_segmentation_assignments "
                        "SET is_active = 0, deactivated_at = datetime('now') "
                        "WHERE id = ?",
                        (a["id"],),
                    )
                    warnings.append(
                        f"Deactivated duplicate segmentation assignment "
                        f"{a['id']!r} for fov_id={row['fov_id']!r}, "
                        f"roi_type_id={row['roi_type_id']!r}"
                    )

            # Check for duplicate active mask assignments
            dup_mask_rows = conn.execute(
                "SELECT fov_id, threshold_mask_id, purpose, COUNT(*) as cnt "
                "FROM fov_mask_assignments "
                "WHERE is_active = 1 "
                "GROUP BY fov_id, threshold_mask_id, purpose "
                "HAVING cnt > 1"
            ).fetchall()

            for row in dup_mask_rows:
                actives = conn.execute(
                    "SELECT id, assigned_at FROM fov_mask_assignments "
                    "WHERE fov_id = ? AND threshold_mask_id = ? "
                    "AND purpose = ? AND is_active = 1 "
                    "ORDER BY assigned_at ASC",
                    (row["fov_id"], row["threshold_mask_id"], row["purpose"]),
                ).fetchall()
                for a in actives[:-1]:
                    conn.execute(
                        "UPDATE fov_mask_assignments "
                        "SET is_active = 0, deactivated_at = datetime('now') "
                        "WHERE id = ?",
                        (a["id"],),
                    )
                    warnings.append(
                        f"Deactivated duplicate mask assignment "
                        f"{a['id']!r} for fov_id={row['fov_id']!r}, "
                        f"threshold_mask_id={row['threshold_mask_id']!r}, "
                        f"purpose={row['purpose']!r}"
                    )

            # ---- Step 8: Post-merge validations ------------------------

            # Foreign key check
            fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
            for fk_row in fk_rows:
                fk_violations.append(tuple(fk_row))
                warnings.append(
                    f"FK violation: table={fk_row['table']}, "
                    f"rowid={fk_row['rowid']}, "
                    f"parent={fk_row['parent']}, "
                    f"fkid={fk_row['fkid']}"
                )

            # Cycle detection: check FOVs with parent_fov_id set
            parent_fovs = conn.execute(
                "SELECT id, parent_fov_id FROM fovs "
                "WHERE parent_fov_id IS NOT NULL"
            ).fetchall()
            for pf in parent_fovs:
                if not self.check_no_cycle(pf["id"], pf["parent_fov_id"]):
                    warnings.append(
                        f"Lineage cycle detected involving FOV {pf['id']!r}"
                    )

            # zarr_path uniqueness among non-deleted FOVs
            dup_zarr = conn.execute(
                "SELECT zarr_path, COUNT(*) as cnt FROM fovs "
                "WHERE zarr_path IS NOT NULL AND status != 'deleted' "
                "GROUP BY zarr_path HAVING cnt > 1"
            ).fetchall()
            for zr in dup_zarr:
                warnings.append(
                    f"Duplicate zarr_path '{zr['zarr_path']}' found "
                    f"among {zr['cnt']} non-deleted FOVs"
                )

            # Identity overlap: cell_identities spanning FOVs from
            # different source experiments (origin_fov_id in different
            # experiments)
            identity_overlap = conn.execute(
                "SELECT ci.id, COUNT(DISTINCT f.experiment_id) as exp_count "
                "FROM cell_identities ci "
                "JOIN fovs f ON ci.origin_fov_id = f.id "
                "GROUP BY ci.id "
                "HAVING exp_count > 1"
            ).fetchall()
            for io in identity_overlap:
                warnings.append(
                    f"Cell identity {io['id']!r} spans FOVs from "
                    f"{io['exp_count']} different experiments"
                )

            # Drop temp table
            conn.execute("DROP TABLE IF EXISTS _merge_eligible_fovs")

        finally:
            # ---- Step 9: Re-enable FK and DETACH -----------------------
            try:
                conn.execute("PRAGMA foreign_keys = ON")
            except Exception:
                pass  # best-effort re-enable
            try:
                conn.execute("DETACH source")
            except Exception:
                pass  # best-effort detach (may already be detached)

        # ---- Step 10: Return merge summary -----------------------------
        return {
            "tables": counts,
            "conflicts": conflicts,
            "warnings": warnings,
            "fk_violations": fk_violations,
        }
