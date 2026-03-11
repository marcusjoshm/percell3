"""Tests for percell4.core.schema — DDL, CHECK constraints, indexes, views."""

from __future__ import annotations

import sqlite3
import uuid

import pytest

from percell4.core.db_types import new_uuid
from percell4.core.schema import (
    SCHEMA_VERSION,
    _configure_connection,
    create_debug_views,
    create_schema,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def conn() -> sqlite3.Connection:
    """Return a configured in-memory database with schema applied."""
    c = sqlite3.connect(":memory:")
    _configure_connection(c)
    create_schema(c)
    return c


def _make_experiment(conn: sqlite3.Connection) -> bytes:
    """Insert and return a minimal experiment row."""
    eid = new_uuid()
    conn.execute(
        "INSERT INTO experiments (id, name) VALUES (?, ?)",
        (eid, "test_exp"),
    )
    return eid


def _make_pipeline_run(conn: sqlite3.Connection) -> bytes:
    """Insert and return a minimal pipeline_runs row."""
    rid = new_uuid()
    conn.execute(
        "INSERT INTO pipeline_runs (id, operation_name) VALUES (?, ?)",
        (rid, "test_op"),
    )
    return rid


def _make_condition(conn: sqlite3.Connection, eid: bytes) -> bytes:
    cid = new_uuid()
    conn.execute(
        "INSERT INTO conditions (id, experiment_id, name) VALUES (?, ?, ?)",
        (cid, eid, "ctrl"),
    )
    return cid


def _make_channel(conn: sqlite3.Connection, eid: bytes) -> bytes:
    chid = new_uuid()
    conn.execute(
        "INSERT INTO channels (id, experiment_id, name) VALUES (?, ?, ?)",
        (chid, eid, "GFP"),
    )
    return chid


def _make_roi_type(
    conn: sqlite3.Connection,
    eid: bytes,
    name: str = "cell",
    parent_type_id: bytes | None = None,
) -> bytes:
    rtid = new_uuid()
    conn.execute(
        "INSERT INTO roi_type_definitions "
        "(id, experiment_id, name, parent_type_id) VALUES (?, ?, ?, ?)",
        (rtid, eid, name, parent_type_id),
    )
    return rtid


def _make_fov(
    conn: sqlite3.Connection,
    eid: bytes,
    *,
    condition_id: bytes | None = None,
    parent_fov_id: bytes | None = None,
    status: str = "imported",
    zarr_path: str | None = None,
) -> bytes:
    fid = new_uuid()
    conn.execute(
        "INSERT INTO fovs "
        "(id, experiment_id, condition_id, parent_fov_id, status, zarr_path) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (fid, eid, condition_id, parent_fov_id, status, zarr_path),
    )
    return fid


def _make_segmentation_set(
    conn: sqlite3.Connection,
    eid: bytes,
    roi_type_id: bytes,
) -> bytes:
    sid = new_uuid()
    conn.execute(
        "INSERT INTO segmentation_sets "
        "(id, experiment_id, produces_roi_type_id, seg_type) "
        "VALUES (?, ?, ?, ?)",
        (sid, eid, roi_type_id, "cellpose"),
    )
    return sid


def _make_threshold_mask(
    conn: sqlite3.Connection,
    fov_id: bytes,
) -> bytes:
    mid = new_uuid()
    conn.execute(
        "INSERT INTO threshold_masks "
        "(id, fov_id, source_channel, method, threshold_value) "
        "VALUES (?, ?, ?, ?, ?)",
        (mid, fov_id, "GFP", "otsu", 42.0),
    )
    return mid


def _make_roi(
    conn: sqlite3.Connection,
    fov_id: bytes,
    roi_type_id: bytes,
    *,
    cell_identity_id: bytes | None = None,
    parent_roi_id: bytes | None = None,
    label_id: int = 1,
) -> bytes:
    rid = new_uuid()
    conn.execute(
        "INSERT INTO rois "
        "(id, fov_id, roi_type_id, cell_identity_id, parent_roi_id, "
        " label_id, bbox_y, bbox_x, bbox_h, bbox_w, area_px) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (rid, fov_id, roi_type_id, cell_identity_id, parent_roi_id,
         label_id, 0, 0, 10, 10, 100),
    )
    return rid


# ===================================================================
# 1. Schema creation
# ===================================================================


class TestSchemaCreation:
    """Verify all tables and indexes are created correctly."""

    EXPECTED_TABLES = frozenset({
        "experiments",
        "conditions",
        "bio_reps",
        "channels",
        "timepoints",
        "roi_type_definitions",
        "pipeline_runs",
        "fovs",
        "cell_identities",
        "rois",
        "segmentation_sets",
        "threshold_masks",
        "fov_segmentation_assignments",
        "fov_mask_assignments",
        "measurements",
        "intensity_groups",
        "cell_group_assignments",
        "fov_status_log",
    })

    def test_all_tables_exist(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        actual = {r["name"] for r in rows}
        assert self.EXPECTED_TABLES == actual

    def test_all_indexes_exist(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        names = {r["name"] for r in rows}
        expected_indexes = {
            "idx_fsa_one_active",
            "idx_fma_one_active",
            "idx_roi_identity_fov",
            "idx_fovs_zarr_path",
            "idx_measurements_roi_channel_scope",
            "idx_measurements_unique_per_run",
            "idx_fovs_parent",
            "idx_fovs_experiment",
            "idx_fovs_condition",
            "idx_fovs_status",
            "idx_rois_fov",
            "idx_rois_type",
        }
        assert expected_indexes.issubset(names)

    def test_no_views_by_default(self, conn: sqlite3.Connection) -> None:
        """create_schema does NOT create debug views."""
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view'"
        ).fetchall()
        assert len(rows) == 0

    def test_debug_views_opt_in(self, conn: sqlite3.Connection) -> None:
        """create_debug_views creates all debug views when called explicitly."""
        create_debug_views(conn)
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view'"
        ).fetchall()
        names = {r["name"] for r in rows}
        expected_views = {
            "debug_rois",
            "debug_fovs",
            "debug_measurements",
            "debug_cell_identities",
            "debug_segmentation_sets",
            "debug_fov_segmentation_assignments",
            "debug_fov_mask_assignments",
        }
        assert expected_views == names

    def test_idempotent_creation(self, conn: sqlite3.Connection) -> None:
        """Calling create_schema twice must not raise."""
        create_schema(conn)  # second call

    def test_schema_version_constant(self) -> None:
        assert SCHEMA_VERSION == "6.0.0"

    def test_fovs_has_pixel_size_um_column(self, conn: sqlite3.Connection) -> None:
        """The fovs table includes a pixel_size_um REAL column."""
        eid = _make_experiment(conn)
        fid = new_uuid()
        conn.execute(
            "INSERT INTO fovs (id, experiment_id, pixel_size_um) "
            "VALUES (?, ?, ?)",
            (fid, eid, 0.325),
        )
        row = conn.execute(
            "SELECT pixel_size_um FROM fovs WHERE id = ?", (fid,)
        ).fetchone()
        assert row["pixel_size_um"] == pytest.approx(0.325)

    def test_fovs_pixel_size_um_nullable(self, conn: sqlite3.Connection) -> None:
        """pixel_size_um accepts NULL."""
        eid = _make_experiment(conn)
        fid = new_uuid()
        conn.execute(
            "INSERT INTO fovs (id, experiment_id) VALUES (?, ?)",
            (fid, eid),
        )
        row = conn.execute(
            "SELECT pixel_size_um FROM fovs WHERE id = ?", (fid,)
        ).fetchone()
        assert row["pixel_size_um"] is None


# ===================================================================
# 2. CHECK constraint violations
# ===================================================================


class TestCheckConstraints:
    """Verify that CHECK constraints reject invalid data."""

    def test_wrong_uuid_length_experiment(
        self, conn: sqlite3.Connection
    ) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO experiments (id, name) VALUES (?, ?)",
                (b"short", "bad"),
            )

    def test_wrong_uuid_length_condition_pk(
        self, conn: sqlite3.Connection
    ) -> None:
        eid = _make_experiment(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO conditions (id, experiment_id, name) "
                "VALUES (?, ?, ?)",
                (b"short", eid, "ctrl"),
            )

    def test_wrong_uuid_length_condition_fk(
        self, conn: sqlite3.Connection
    ) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO conditions (id, experiment_id, name) "
                "VALUES (?, ?, ?)",
                (new_uuid(), b"bad_fk", "ctrl"),
            )

    def test_invalid_fov_status(self, conn: sqlite3.Connection) -> None:
        eid = _make_experiment(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO fovs (id, experiment_id, status) "
                "VALUES (?, ?, ?)",
                (new_uuid(), eid, "bogus_status"),
            )

    def test_invalid_measurement_scope(
        self, conn: sqlite3.Connection
    ) -> None:
        eid = _make_experiment(conn)
        rtid = _make_roi_type(conn, eid)
        fid = _make_fov(conn, eid)
        chid = _make_channel(conn, eid)
        rid = _make_roi(conn, fid, rtid)
        prid = _make_pipeline_run(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO measurements "
                "(id, roi_id, channel_id, metric, scope, value, "
                " pipeline_run_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (new_uuid(), rid, chid, "mean", "invalid_scope", 1.0, prid),
            )

    def test_self_referencing_fov_parent_rejected(
        self, conn: sqlite3.Connection
    ) -> None:
        eid = _make_experiment(conn)
        fov_id = new_uuid()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO fovs (id, experiment_id, parent_fov_id) "
                "VALUES (?, ?, ?)",
                (fov_id, eid, fov_id),
            )

    def test_invalid_threshold_mask_status(
        self, conn: sqlite3.Connection
    ) -> None:
        eid = _make_experiment(conn)
        fid = _make_fov(conn, eid)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO threshold_masks "
                "(id, fov_id, source_channel, method, threshold_value, "
                " status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (new_uuid(), fid, "GFP", "otsu", 42.0, "bogus"),
            )

    def test_invalid_pipeline_run_status(
        self, conn: sqlite3.Connection
    ) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO pipeline_runs (id, operation_name, status) "
                "VALUES (?, ?, ?)",
                (new_uuid(), "test", "bogus"),
            )

    def test_invalid_fov_mask_assignment_purpose(
        self, conn: sqlite3.Connection
    ) -> None:
        eid = _make_experiment(conn)
        fid = _make_fov(conn, eid)
        mid = _make_threshold_mask(conn, fid)
        prid = _make_pipeline_run(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO fov_mask_assignments "
                "(id, fov_id, threshold_mask_id, purpose, "
                " pipeline_run_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (new_uuid(), fid, mid, "invalid_purpose", prid),
            )

    def test_invalid_fsa_is_active(self, conn: sqlite3.Connection) -> None:
        eid = _make_experiment(conn)
        rtid = _make_roi_type(conn, eid)
        fid = _make_fov(conn, eid)
        sid = _make_segmentation_set(conn, eid, rtid)
        prid = _make_pipeline_run(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO fov_segmentation_assignments "
                "(id, fov_id, segmentation_set_id, roi_type_id, "
                " is_active, pipeline_run_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (new_uuid(), fid, sid, rtid, 2, prid),
            )

    def test_invalid_json_derivation_params(
        self, conn: sqlite3.Connection
    ) -> None:
        eid = _make_experiment(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO fovs "
                "(id, experiment_id, derivation_params) "
                "VALUES (?, ?, ?)",
                (new_uuid(), eid, "not-valid-json"),
            )

    def test_valid_json_derivation_params_accepted(
        self, conn: sqlite3.Connection
    ) -> None:
        eid = _make_experiment(conn)
        fid = new_uuid()
        conn.execute(
            "INSERT INTO fovs "
            "(id, experiment_id, derivation_params) "
            "VALUES (?, ?, ?)",
            (fid, eid, '{"op": "mask_subtract"}'),
        )
        row = conn.execute(
            "SELECT derivation_params FROM fovs WHERE id = ?", (fid,)
        ).fetchone()
        assert row["derivation_params"] == '{"op": "mask_subtract"}'

    def test_null_derivation_params_accepted(
        self, conn: sqlite3.Connection
    ) -> None:
        eid = _make_experiment(conn)
        fid = new_uuid()
        conn.execute(
            "INSERT INTO fovs (id, experiment_id) VALUES (?, ?)",
            (fid, eid),
        )
        row = conn.execute(
            "SELECT derivation_params FROM fovs WHERE id = ?", (fid,)
        ).fetchone()
        assert row["derivation_params"] is None


# ===================================================================
# 3. Partial unique index enforcement
# ===================================================================


class TestPartialUniqueIndexes:
    """Verify partial unique indexes enforce business rules."""

    def test_two_active_fsa_same_fov_roi_type_rejected(
        self, conn: sqlite3.Connection
    ) -> None:
        eid = _make_experiment(conn)
        rtid = _make_roi_type(conn, eid)
        fid = _make_fov(conn, eid)
        sid1 = _make_segmentation_set(conn, eid, rtid)
        sid2 = _make_segmentation_set(conn, eid, rtid)
        prid = _make_pipeline_run(conn)

        # First active assignment — succeeds
        conn.execute(
            "INSERT INTO fov_segmentation_assignments "
            "(id, fov_id, segmentation_set_id, roi_type_id, is_active, "
            " pipeline_run_id) "
            "VALUES (?, ?, ?, ?, 1, ?)",
            (new_uuid(), fid, sid1, rtid, prid),
        )

        # Second active assignment for same (fov, roi_type) — rejected
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO fov_segmentation_assignments "
                "(id, fov_id, segmentation_set_id, roi_type_id, is_active, "
                " pipeline_run_id) "
                "VALUES (?, ?, ?, ?, 1, ?)",
                (new_uuid(), fid, sid2, rtid, prid),
            )

    def test_inactive_fsa_does_not_conflict(
        self, conn: sqlite3.Connection
    ) -> None:
        eid = _make_experiment(conn)
        rtid = _make_roi_type(conn, eid)
        fid = _make_fov(conn, eid)
        sid1 = _make_segmentation_set(conn, eid, rtid)
        sid2 = _make_segmentation_set(conn, eid, rtid)
        prid = _make_pipeline_run(conn)

        # First active assignment
        conn.execute(
            "INSERT INTO fov_segmentation_assignments "
            "(id, fov_id, segmentation_set_id, roi_type_id, is_active, "
            " pipeline_run_id) "
            "VALUES (?, ?, ?, ?, 1, ?)",
            (new_uuid(), fid, sid1, rtid, prid),
        )

        # Second assignment but inactive — allowed
        conn.execute(
            "INSERT INTO fov_segmentation_assignments "
            "(id, fov_id, segmentation_set_id, roi_type_id, is_active, "
            " pipeline_run_id) "
            "VALUES (?, ?, ?, ?, 0, ?)",
            (new_uuid(), fid, sid2, rtid, prid),
        )

    def test_two_active_fma_same_mask_purpose_rejected(
        self, conn: sqlite3.Connection
    ) -> None:
        eid = _make_experiment(conn)
        fid = _make_fov(conn, eid)
        mid = _make_threshold_mask(conn, fid)
        prid = _make_pipeline_run(conn)

        # First active
        conn.execute(
            "INSERT INTO fov_mask_assignments "
            "(id, fov_id, threshold_mask_id, purpose, is_active, "
            " pipeline_run_id) "
            "VALUES (?, ?, ?, 'measurement_scope', 1, ?)",
            (new_uuid(), fid, mid, prid),
        )

        # Duplicate active — rejected
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO fov_mask_assignments "
                "(id, fov_id, threshold_mask_id, purpose, is_active, "
                " pipeline_run_id) "
                "VALUES (?, ?, ?, 'measurement_scope', 1, ?)",
                (new_uuid(), fid, mid, prid),
            )

    def test_duplicate_zarr_path_live_fovs_rejected(
        self, conn: sqlite3.Connection
    ) -> None:
        eid = _make_experiment(conn)
        _make_fov(conn, eid, zarr_path="images/abc123")

        with pytest.raises(sqlite3.IntegrityError):
            _make_fov(conn, eid, zarr_path="images/abc123")

    def test_duplicate_zarr_path_deleted_fov_allowed(
        self, conn: sqlite3.Connection
    ) -> None:
        eid = _make_experiment(conn)
        _make_fov(conn, eid, zarr_path="images/reuse", status="deleted")
        # Same path, live FOV — should succeed because old one is 'deleted'
        _make_fov(conn, eid, zarr_path="images/reuse", status="imported")

    def test_duplicate_cell_identity_fov_rejected(
        self, conn: sqlite3.Connection
    ) -> None:
        eid = _make_experiment(conn)
        rtid = _make_roi_type(conn, eid)
        fid = _make_fov(conn, eid)

        ci_id = new_uuid()
        conn.execute(
            "INSERT INTO cell_identities "
            "(id, origin_fov_id, roi_type_id) VALUES (?, ?, ?)",
            (ci_id, fid, rtid),
        )

        # First ROI with cell_identity in this FOV
        _make_roi(conn, fid, rtid, cell_identity_id=ci_id, label_id=1)

        # Second ROI with same cell_identity in same FOV — rejected
        with pytest.raises(sqlite3.IntegrityError):
            _make_roi(conn, fid, rtid, cell_identity_id=ci_id, label_id=2)


# ===================================================================
# 4. Debug views
# ===================================================================


class TestDebugViews:
    """Verify debug views return human-readable data."""

    @pytest.fixture(autouse=True)
    def _create_views(self, conn: sqlite3.Connection) -> None:
        """Explicitly create debug views for these tests."""
        create_debug_views(conn)

    def test_debug_fovs_returns_uuid_strings(
        self, conn: sqlite3.Connection
    ) -> None:
        eid = _make_experiment(conn)
        fid = _make_fov(conn, eid, status="imported")

        rows = conn.execute("SELECT * FROM debug_fovs").fetchall()
        assert len(rows) == 1

        row = rows[0]
        # id_hex should be a readable UUID string
        expected_hex = str(uuid.UUID(bytes=fid))
        assert row["id_hex"] == expected_hex
        assert row["status"] == "imported"

    def test_debug_rois_returns_uuid_strings(
        self, conn: sqlite3.Connection
    ) -> None:
        eid = _make_experiment(conn)
        rtid = _make_roi_type(conn, eid)
        fid = _make_fov(conn, eid)
        roi_id = _make_roi(conn, fid, rtid)

        rows = conn.execute("SELECT * FROM debug_rois").fetchall()
        assert len(rows) == 1

        row = rows[0]
        assert row["id_hex"] == str(uuid.UUID(bytes=roi_id))
        assert row["fov_hex"] == str(uuid.UUID(bytes=fid))
        assert row["type_hex"] == str(uuid.UUID(bytes=rtid))
        assert row["label_id"] == 1
        assert row["area_px"] == 100

    def test_debug_measurements_returns_data(
        self, conn: sqlite3.Connection
    ) -> None:
        eid = _make_experiment(conn)
        rtid = _make_roi_type(conn, eid)
        fid = _make_fov(conn, eid)
        chid = _make_channel(conn, eid)
        rid = _make_roi(conn, fid, rtid)
        prid = _make_pipeline_run(conn)

        mid = new_uuid()
        conn.execute(
            "INSERT INTO measurements "
            "(id, roi_id, channel_id, metric, scope, value, "
            " pipeline_run_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (mid, rid, chid, "mean", "whole_roi", 42.5, prid),
        )

        rows = conn.execute("SELECT * FROM debug_measurements").fetchall()
        assert len(rows) == 1
        assert rows[0]["metric"] == "mean"
        assert rows[0]["value"] == 42.5
        assert rows[0]["roi_hex"] == str(uuid.UUID(bytes=rid))
        assert rows[0]["run_hex"] == str(uuid.UUID(bytes=prid))

    def test_debug_cell_identities_returns_data(
        self, conn: sqlite3.Connection
    ) -> None:
        eid = _make_experiment(conn)
        rtid = _make_roi_type(conn, eid)
        fid = _make_fov(conn, eid)
        ci_id = new_uuid()
        conn.execute(
            "INSERT INTO cell_identities "
            "(id, origin_fov_id, roi_type_id) VALUES (?, ?, ?)",
            (ci_id, fid, rtid),
        )

        rows = conn.execute(
            "SELECT * FROM debug_cell_identities"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["id_hex"] == str(uuid.UUID(bytes=ci_id))
        assert rows[0]["origin_fov_hex"] == str(uuid.UUID(bytes=fid))

    def test_debug_segmentation_sets_returns_data(
        self, conn: sqlite3.Connection
    ) -> None:
        eid = _make_experiment(conn)
        rtid = _make_roi_type(conn, eid)
        sid = _make_segmentation_set(conn, eid, rtid)

        rows = conn.execute(
            "SELECT * FROM debug_segmentation_sets"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["id_hex"] == str(uuid.UUID(bytes=sid))
        assert rows[0]["seg_type"] == "cellpose"

    def test_debug_fov_segmentation_assignments_returns_data(
        self, conn: sqlite3.Connection
    ) -> None:
        eid = _make_experiment(conn)
        rtid = _make_roi_type(conn, eid)
        fid = _make_fov(conn, eid)
        sid = _make_segmentation_set(conn, eid, rtid)
        prid = _make_pipeline_run(conn)

        aid = new_uuid()
        conn.execute(
            "INSERT INTO fov_segmentation_assignments "
            "(id, fov_id, segmentation_set_id, roi_type_id, "
            " pipeline_run_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (aid, fid, sid, rtid, prid),
        )

        rows = conn.execute(
            "SELECT * FROM debug_fov_segmentation_assignments"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["id_hex"] == str(uuid.UUID(bytes=aid))
        assert rows[0]["fov_hex"] == str(uuid.UUID(bytes=fid))
        assert rows[0]["is_active"] == 1

    def test_debug_fov_mask_assignments_returns_data(
        self, conn: sqlite3.Connection
    ) -> None:
        eid = _make_experiment(conn)
        fid = _make_fov(conn, eid)
        mid = _make_threshold_mask(conn, fid)
        prid = _make_pipeline_run(conn)

        aid = new_uuid()
        conn.execute(
            "INSERT INTO fov_mask_assignments "
            "(id, fov_id, threshold_mask_id, purpose, pipeline_run_id) "
            "VALUES (?, ?, ?, 'measurement_scope', ?)",
            (aid, fid, mid, prid),
        )

        rows = conn.execute(
            "SELECT * FROM debug_fov_mask_assignments"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["id_hex"] == str(uuid.UUID(bytes=aid))
        assert rows[0]["purpose"] == "measurement_scope"


# ===================================================================
# 5. uuid_str function
# ===================================================================


class TestUuidStrFunction:
    """Verify the uuid_str SQLite UDF."""

    def test_uuid_str_converts_bytes(self, conn: sqlite3.Connection) -> None:
        uid = new_uuid()
        row = conn.execute("SELECT uuid_str(?) AS val", (uid,)).fetchone()
        assert row["val"] == str(uuid.UUID(bytes=uid))

    def test_uuid_str_handles_null(self, conn: sqlite3.Connection) -> None:
        row = conn.execute("SELECT uuid_str(NULL) AS val").fetchone()
        assert row["val"] is None


# ===================================================================
# 6. _configure_connection PRAGMAs
# ===================================================================


class TestConfigureConnection:
    """Verify _configure_connection sets correct PRAGMAs."""

    def test_journal_mode_wal(self) -> None:
        c = sqlite3.connect(":memory:")
        _configure_connection(c)
        row = c.execute("PRAGMA journal_mode").fetchone()
        # In-memory databases may report "memory" instead of "wal",
        # so we test with a file-based database instead.
        # For in-memory, just verify no error was raised.
        # The real test is below with a temp file.

    def test_foreign_keys_enabled(self) -> None:
        c = sqlite3.connect(":memory:")
        _configure_connection(c)
        row = c.execute("PRAGMA foreign_keys").fetchone()
        assert row[0] == 1

    def test_busy_timeout(self) -> None:
        c = sqlite3.connect(":memory:")
        _configure_connection(c)
        row = c.execute("PRAGMA busy_timeout").fetchone()
        assert row[0] == 30000

    def test_synchronous_normal(self) -> None:
        c = sqlite3.connect(":memory:")
        _configure_connection(c)
        row = c.execute("PRAGMA synchronous").fetchone()
        # NORMAL = 1
        assert row[0] == 1

    def test_cache_size(self) -> None:
        c = sqlite3.connect(":memory:")
        _configure_connection(c)
        row = c.execute("PRAGMA cache_size").fetchone()
        assert row[0] == -64000

    def test_row_factory_set(self) -> None:
        c = sqlite3.connect(":memory:")
        _configure_connection(c)
        assert c.row_factory is sqlite3.Row

    def test_journal_mode_wal_on_file(self, tmp_path) -> None:
        db_path = tmp_path / "test.db"
        c = sqlite3.connect(str(db_path))
        _configure_connection(c)
        row = c.execute("PRAGMA journal_mode").fetchone()
        assert row[0] == "wal"
        c.close()


# ===================================================================
# 7. Default values
# ===================================================================


class TestDefaults:
    """Verify default values are applied correctly."""

    def test_experiment_schema_version_default(
        self, conn: sqlite3.Connection
    ) -> None:
        eid = _make_experiment(conn)
        row = conn.execute(
            "SELECT schema_version FROM experiments WHERE id = ?", (eid,)
        ).fetchone()
        assert row["schema_version"] == "6.0.0"

    def test_fov_status_default_pending(
        self, conn: sqlite3.Connection
    ) -> None:
        eid = _make_experiment(conn)
        fid = new_uuid()
        conn.execute(
            "INSERT INTO fovs (id, experiment_id) VALUES (?, ?)",
            (fid, eid),
        )
        row = conn.execute(
            "SELECT status FROM fovs WHERE id = ?", (fid,)
        ).fetchone()
        assert row["status"] == "pending"

    def test_pipeline_run_status_default_running(
        self, conn: sqlite3.Connection
    ) -> None:
        prid = _make_pipeline_run(conn)
        row = conn.execute(
            "SELECT status FROM pipeline_runs WHERE id = ?", (prid,)
        ).fetchone()
        assert row["status"] == "running"

    def test_fsa_is_active_default_1(
        self, conn: sqlite3.Connection
    ) -> None:
        eid = _make_experiment(conn)
        rtid = _make_roi_type(conn, eid)
        fid = _make_fov(conn, eid)
        sid = _make_segmentation_set(conn, eid, rtid)
        prid = _make_pipeline_run(conn)
        aid = new_uuid()
        conn.execute(
            "INSERT INTO fov_segmentation_assignments "
            "(id, fov_id, segmentation_set_id, roi_type_id, "
            " pipeline_run_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (aid, fid, sid, rtid, prid),
        )
        row = conn.execute(
            "SELECT is_active FROM fov_segmentation_assignments "
            "WHERE id = ?",
            (aid,),
        ).fetchone()
        assert row["is_active"] == 1

    def test_created_at_populated(self, conn: sqlite3.Connection) -> None:
        eid = _make_experiment(conn)
        row = conn.execute(
            "SELECT created_at FROM experiments WHERE id = ?", (eid,)
        ).fetchone()
        assert row["created_at"] is not None
        # Should look like a datetime string
        assert "20" in row["created_at"]


# ===================================================================
# 8. Foreign key enforcement
# ===================================================================


class TestForeignKeys:
    """Verify FK constraints are enforced."""

    def test_fov_requires_valid_experiment(
        self, conn: sqlite3.Connection
    ) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO fovs (id, experiment_id) VALUES (?, ?)",
                (new_uuid(), new_uuid()),  # nonexistent experiment
            )

    def test_condition_requires_valid_experiment(
        self, conn: sqlite3.Connection
    ) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO conditions (id, experiment_id, name) "
                "VALUES (?, ?, ?)",
                (new_uuid(), new_uuid(), "ctrl"),
            )

    def test_roi_requires_valid_fov(
        self, conn: sqlite3.Connection
    ) -> None:
        eid = _make_experiment(conn)
        rtid = _make_roi_type(conn, eid)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO rois "
                "(id, fov_id, roi_type_id, label_id, "
                " bbox_y, bbox_x, bbox_h, bbox_w, area_px) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (new_uuid(), new_uuid(), rtid, 1, 0, 0, 10, 10, 100),
            )

    def test_measurement_requires_valid_pipeline_run(
        self, conn: sqlite3.Connection
    ) -> None:
        eid = _make_experiment(conn)
        rtid = _make_roi_type(conn, eid)
        fid = _make_fov(conn, eid)
        chid = _make_channel(conn, eid)
        rid = _make_roi(conn, fid, rtid)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO measurements "
                "(id, roi_id, channel_id, metric, scope, value, "
                " pipeline_run_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (new_uuid(), rid, chid, "mean", "whole_roi", 1.0,
                 new_uuid()),  # nonexistent run
            )
