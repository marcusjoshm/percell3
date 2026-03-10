"""ExperimentDB — SQLite CRUD and connection management for PerCell 4.

Provides connection lifecycle (open/close/context manager), SAVEPOINT-based
nested transactions, and typed CRUD methods for all entity tables.

This module sits at the hexagonal boundary: it depends ONLY on the Python
stdlib and percell4.core internals.  No zarr, numpy, or dask imports are
permitted here.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from percell4.core.constants import DEFAULT_BATCH_SIZE
from percell4.core.schema import SCHEMA_VERSION, _configure_connection, create_schema

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
    ) -> int:
        """Insert an FOV record. Returns rowcount."""
        cur = self.connection.execute(
            "INSERT INTO fovs "
            "(id, experiment_id, condition_id, bio_rep_id, parent_fov_id, "
            " derivation_op, derivation_params, status, auto_name, "
            " zarr_path, timepoint_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                id, experiment_id, condition_id, bio_rep_id, parent_fov_id,
                derivation_op, derivation_params, status, auto_name,
                zarr_path, timepoint_id,
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
