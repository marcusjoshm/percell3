"""SQLite DDL and schema creation for the PerCell 4 database.

Defines all CREATE TABLE, CREATE INDEX, and CREATE VIEW statements
for schema version 5.0.0.  The ``create_schema`` function is the
single entry-point used by ExperimentStore to initialise a new
experiment database.
"""

from __future__ import annotations

import sqlite3
import uuid

# ---------------------------------------------------------------------------
# Schema version
# ---------------------------------------------------------------------------

SCHEMA_VERSION: str = "5.0.0"

# ---------------------------------------------------------------------------
# Table DDL (topological order — parents before children)
# ---------------------------------------------------------------------------

_TABLE_DDL: tuple[str, ...] = (
    # -- experiments --
    """
    CREATE TABLE IF NOT EXISTS experiments (
        id              BLOB(16) PRIMARY KEY CHECK(length(id) = 16),
        name            TEXT NOT NULL,
        schema_version  TEXT NOT NULL DEFAULT '5.0.0',
        config_hash     TEXT,
        created_at      TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # -- conditions --
    """
    CREATE TABLE IF NOT EXISTS conditions (
        id              BLOB(16) PRIMARY KEY CHECK(length(id) = 16),
        experiment_id   BLOB(16) NOT NULL REFERENCES experiments
                            CHECK(length(experiment_id) = 16),
        name            TEXT NOT NULL,
        UNIQUE(experiment_id, name)
    )
    """,
    # -- bio_reps --
    """
    CREATE TABLE IF NOT EXISTS bio_reps (
        id              BLOB(16) PRIMARY KEY CHECK(length(id) = 16),
        experiment_id   BLOB(16) NOT NULL REFERENCES experiments
                            CHECK(length(experiment_id) = 16),
        condition_id    BLOB(16) NOT NULL REFERENCES conditions
                            CHECK(length(condition_id) = 16),
        name            TEXT NOT NULL,
        UNIQUE(experiment_id, name)
    )
    """,
    # -- channels --
    """
    CREATE TABLE IF NOT EXISTS channels (
        id              BLOB(16) PRIMARY KEY CHECK(length(id) = 16),
        experiment_id   BLOB(16) NOT NULL REFERENCES experiments
                            CHECK(length(experiment_id) = 16),
        name            TEXT NOT NULL,
        role            TEXT,
        color           TEXT,
        display_order   INTEGER NOT NULL DEFAULT 0,
        UNIQUE(experiment_id, name)
    )
    """,
    # -- timepoints --
    """
    CREATE TABLE IF NOT EXISTS timepoints (
        id              BLOB(16) PRIMARY KEY CHECK(length(id) = 16),
        experiment_id   BLOB(16) NOT NULL REFERENCES experiments
                            CHECK(length(experiment_id) = 16),
        name            TEXT NOT NULL,
        time_seconds    REAL,
        display_order   INTEGER NOT NULL DEFAULT 0,
        UNIQUE(experiment_id, name)
    )
    """,
    # -- roi_type_definitions --
    """
    CREATE TABLE IF NOT EXISTS roi_type_definitions (
        id              BLOB(16) PRIMARY KEY CHECK(length(id) = 16),
        experiment_id   BLOB(16) NOT NULL REFERENCES experiments
                            CHECK(length(experiment_id) = 16),
        name            TEXT NOT NULL,
        parent_type_id  BLOB(16) REFERENCES roi_type_definitions
                            CHECK(parent_type_id IS NULL
                                  OR length(parent_type_id) = 16),
        UNIQUE(experiment_id, name)
    )
    """,
    # -- pipeline_runs  (must precede tables that reference it) --
    """
    CREATE TABLE IF NOT EXISTS pipeline_runs (
        id              BLOB(16) PRIMARY KEY CHECK(length(id) = 16),
        operation_name  TEXT NOT NULL,
        config_snapshot TEXT CHECK(config_snapshot IS NULL
                                  OR json_valid(config_snapshot)),
        status          TEXT NOT NULL DEFAULT 'running'
                            CHECK(status IN ('running', 'completed', 'failed')),
        started_at      TEXT NOT NULL DEFAULT (datetime('now')),
        completed_at    TEXT,
        error_message   TEXT
    )
    """,
    # -- fovs --
    """
    CREATE TABLE IF NOT EXISTS fovs (
        id              BLOB(16) PRIMARY KEY CHECK(length(id) = 16),
        experiment_id   BLOB(16) NOT NULL REFERENCES experiments
                            CHECK(length(experiment_id) = 16),
        condition_id    BLOB(16) REFERENCES conditions
                            CHECK(condition_id IS NULL
                                  OR length(condition_id) = 16),
        bio_rep_id      BLOB(16) REFERENCES bio_reps
                            CHECK(bio_rep_id IS NULL
                                  OR length(bio_rep_id) = 16),
        parent_fov_id   BLOB(16) REFERENCES fovs
                            CHECK(parent_fov_id IS NULL
                                  OR length(parent_fov_id) = 16),
        derivation_op   TEXT,
        derivation_params TEXT
                            CHECK(derivation_params IS NULL
                                  OR json_valid(derivation_params)),
        status          TEXT NOT NULL DEFAULT 'pending'
                            CHECK(status IN (
                                'pending', 'imported', 'segmented',
                                'measured', 'analyzing', 'qc_pending',
                                'qc_done', 'stale', 'deleting', 'deleted'
                            )),
        auto_name       TEXT,
        zarr_path       TEXT,
        timepoint_id    BLOB(16) REFERENCES timepoints
                            CHECK(timepoint_id IS NULL
                                  OR length(timepoint_id) = 16),
        created_at      TEXT NOT NULL DEFAULT (datetime('now')),
        CHECK(id != parent_fov_id)
    )
    """,
    # -- cell_identities --
    """
    CREATE TABLE IF NOT EXISTS cell_identities (
        id              BLOB(16) PRIMARY KEY CHECK(length(id) = 16),
        origin_fov_id   BLOB(16) NOT NULL REFERENCES fovs
                            CHECK(length(origin_fov_id) = 16),
        roi_type_id     BLOB(16) NOT NULL REFERENCES roi_type_definitions
                            CHECK(length(roi_type_id) = 16),
        created_at      TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # -- rois --
    """
    CREATE TABLE IF NOT EXISTS rois (
        id                  BLOB(16) PRIMARY KEY CHECK(length(id) = 16),
        fov_id              BLOB(16) NOT NULL REFERENCES fovs
                                CHECK(length(fov_id) = 16),
        roi_type_id         BLOB(16) NOT NULL REFERENCES roi_type_definitions
                                CHECK(length(roi_type_id) = 16),
        cell_identity_id    BLOB(16) REFERENCES cell_identities
                                CHECK(cell_identity_id IS NULL
                                      OR length(cell_identity_id) = 16),
        parent_roi_id       BLOB(16) REFERENCES rois
                                CHECK(parent_roi_id IS NULL
                                      OR length(parent_roi_id) = 16),
        label_id            INTEGER NOT NULL,
        bbox_y              INTEGER NOT NULL,
        bbox_x              INTEGER NOT NULL,
        bbox_h              INTEGER NOT NULL,
        bbox_w              INTEGER NOT NULL,
        area_px             INTEGER NOT NULL
    )
    """,
    # -- segmentation_sets --
    """
    CREATE TABLE IF NOT EXISTS segmentation_sets (
        id                   BLOB(16) PRIMARY KEY CHECK(length(id) = 16),
        experiment_id        BLOB(16) NOT NULL REFERENCES experiments
                                 CHECK(length(experiment_id) = 16),
        produces_roi_type_id BLOB(16) NOT NULL REFERENCES roi_type_definitions
                                 CHECK(length(produces_roi_type_id) = 16),
        seg_type             TEXT NOT NULL,
        op_config_name       TEXT,
        source_channel       TEXT,
        model_name           TEXT,
        parameters           TEXT CHECK(parameters IS NULL
                                       OR json_valid(parameters)),
        fov_count            INTEGER NOT NULL DEFAULT 0,
        total_roi_count      INTEGER NOT NULL DEFAULT 0,
        created_at           TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # -- threshold_masks --
    """
    CREATE TABLE IF NOT EXISTS threshold_masks (
        id                  BLOB(16) PRIMARY KEY CHECK(length(id) = 16),
        fov_id              BLOB(16) NOT NULL REFERENCES fovs
                                CHECK(length(fov_id) = 16),
        source_channel      TEXT NOT NULL,
        grouping_channel    TEXT,
        method              TEXT NOT NULL,
        threshold_value     REAL NOT NULL,
        histogram           TEXT CHECK(histogram IS NULL
                                      OR json_valid(histogram)),
        zarr_path           TEXT,
        status              TEXT NOT NULL DEFAULT 'pending'
                                CHECK(status IN (
                                    'pending', 'computed', 'applied', 'error'
                                )),
        created_at          TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # -- fov_segmentation_assignments --
    """
    CREATE TABLE IF NOT EXISTS fov_segmentation_assignments (
        id                  BLOB(16) PRIMARY KEY CHECK(length(id) = 16),
        fov_id              BLOB(16) NOT NULL REFERENCES fovs
                                CHECK(length(fov_id) = 16),
        segmentation_set_id BLOB(16) NOT NULL REFERENCES segmentation_sets
                                CHECK(length(segmentation_set_id) = 16),
        roi_type_id         BLOB(16) NOT NULL REFERENCES roi_type_definitions
                                CHECK(length(roi_type_id) = 16),
        is_active           INTEGER NOT NULL DEFAULT 1
                                CHECK(is_active IN (0, 1)),
        pipeline_run_id     BLOB(16) NOT NULL REFERENCES pipeline_runs
                                CHECK(length(pipeline_run_id) = 16),
        assigned_by         TEXT,
        assigned_at         TEXT NOT NULL DEFAULT (datetime('now')),
        deactivated_at      TEXT,
        width               INTEGER,
        height              INTEGER,
        roi_count           INTEGER
    )
    """,
    # -- fov_mask_assignments --
    """
    CREATE TABLE IF NOT EXISTS fov_mask_assignments (
        id                  BLOB(16) PRIMARY KEY CHECK(length(id) = 16),
        fov_id              BLOB(16) NOT NULL REFERENCES fovs
                                CHECK(length(fov_id) = 16),
        threshold_mask_id   BLOB(16) NOT NULL REFERENCES threshold_masks
                                CHECK(length(threshold_mask_id) = 16),
        purpose             TEXT NOT NULL
                                CHECK(purpose IN (
                                    'measurement_scope',
                                    'background_estimation',
                                    'fov_derivation'
                                )),
        is_active           INTEGER NOT NULL DEFAULT 1
                                CHECK(is_active IN (0, 1)),
        pipeline_run_id     BLOB(16) NOT NULL REFERENCES pipeline_runs
                                CHECK(length(pipeline_run_id) = 16),
        assigned_by         TEXT,
        assigned_at         TEXT NOT NULL DEFAULT (datetime('now')),
        deactivated_at      TEXT
    )
    """,
    # -- measurements --
    """
    CREATE TABLE IF NOT EXISTS measurements (
        id              BLOB(16) PRIMARY KEY CHECK(length(id) = 16),
        roi_id          BLOB(16) NOT NULL REFERENCES rois
                            CHECK(length(roi_id) = 16),
        channel_id      BLOB(16) NOT NULL REFERENCES channels
                            CHECK(length(channel_id) = 16),
        metric          TEXT NOT NULL,
        scope           TEXT NOT NULL
                            CHECK(scope IN (
                                'whole_roi', 'mask_inside', 'mask_outside'
                            )),
        value           REAL NOT NULL,
        pipeline_run_id BLOB(16) NOT NULL REFERENCES pipeline_runs
                            CHECK(length(pipeline_run_id) = 16)
    )
    """,
    # -- intensity_groups --
    """
    CREATE TABLE IF NOT EXISTS intensity_groups (
        id              BLOB(16) PRIMARY KEY CHECK(length(id) = 16),
        experiment_id   BLOB(16) NOT NULL REFERENCES experiments
                            CHECK(length(experiment_id) = 16),
        name            TEXT NOT NULL,
        channel_id      BLOB(16) NOT NULL REFERENCES channels
                            CHECK(length(channel_id) = 16),
        group_index     INTEGER,
        lower_bound     REAL,
        upper_bound     REAL,
        color_hex       TEXT,
        pipeline_run_id BLOB(16) NOT NULL REFERENCES pipeline_runs
                            CHECK(length(pipeline_run_id) = 16),
        created_at      TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # -- cell_group_assignments --
    """
    CREATE TABLE IF NOT EXISTS cell_group_assignments (
        id                  BLOB(16) PRIMARY KEY CHECK(length(id) = 16),
        intensity_group_id  BLOB(16) NOT NULL REFERENCES intensity_groups
                                CHECK(length(intensity_group_id) = 16),
        roi_id              BLOB(16) NOT NULL REFERENCES rois
                                CHECK(length(roi_id) = 16),
        pipeline_run_id     BLOB(16) NOT NULL REFERENCES pipeline_runs
                                CHECK(length(pipeline_run_id) = 16)
    )
    """,
    # -- fov_status_log  (integer PK, append-only) --
    """
    CREATE TABLE IF NOT EXISTS fov_status_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        fov_id      BLOB(16) NOT NULL REFERENCES fovs
                        CHECK(length(fov_id) = 16),
        old_status  TEXT,
        new_status  TEXT NOT NULL,
        message     TEXT,
        created_at  TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
)

# ---------------------------------------------------------------------------
# Index DDL
# ---------------------------------------------------------------------------

_INDEX_DDL: tuple[str, ...] = (
    # -- partial unique indexes (enforce business rules) --
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_fsa_one_active
        ON fov_segmentation_assignments(fov_id, roi_type_id)
        WHERE is_active = 1
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_fma_one_active
        ON fov_mask_assignments(fov_id, threshold_mask_id, purpose)
        WHERE is_active = 1
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_roi_identity_fov
        ON rois(cell_identity_id, fov_id)
        WHERE cell_identity_id IS NOT NULL
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_fovs_zarr_path
        ON fovs(zarr_path)
        WHERE zarr_path IS NOT NULL AND status NOT IN ('deleted')
    """,
    # -- measurements --
    """
    CREATE INDEX IF NOT EXISTS idx_measurements_roi_channel_scope
        ON measurements(roi_id, channel_id, scope)
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_measurements_unique_per_run
        ON measurements(roi_id, channel_id, metric, scope, pipeline_run_id)
    """,
    # -- fovs --
    """
    CREATE INDEX IF NOT EXISTS idx_fovs_parent
        ON fovs(parent_fov_id)
        WHERE parent_fov_id IS NOT NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_fovs_experiment
        ON fovs(experiment_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_fovs_condition
        ON fovs(condition_id)
        WHERE condition_id IS NOT NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_fovs_status
        ON fovs(status)
    """,
    # -- rois --
    """
    CREATE INDEX IF NOT EXISTS idx_rois_fov
        ON rois(fov_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_rois_type
        ON rois(roi_type_id)
    """,
)

# ---------------------------------------------------------------------------
# Debug view DDL  (require the uuid_str UDF registered by _configure_connection)
# ---------------------------------------------------------------------------

_VIEW_DDL: tuple[str, ...] = (
    """
    CREATE VIEW IF NOT EXISTS debug_rois AS
    SELECT uuid_str(id)         AS id_hex,
           uuid_str(fov_id)     AS fov_hex,
           uuid_str(roi_type_id) AS type_hex,
           uuid_str(cell_identity_id) AS identity_hex,
           uuid_str(parent_roi_id) AS parent_hex,
           label_id,
           bbox_y, bbox_x, bbox_h, bbox_w,
           area_px
    FROM rois
    """,
    """
    CREATE VIEW IF NOT EXISTS debug_fovs AS
    SELECT uuid_str(id)             AS id_hex,
           uuid_str(experiment_id)  AS experiment_hex,
           uuid_str(condition_id)   AS condition_hex,
           uuid_str(bio_rep_id)     AS bio_rep_hex,
           uuid_str(parent_fov_id)  AS parent_hex,
           auto_name,
           status,
           zarr_path,
           created_at
    FROM fovs
    """,
    """
    CREATE VIEW IF NOT EXISTS debug_measurements AS
    SELECT uuid_str(id)              AS id_hex,
           uuid_str(roi_id)          AS roi_hex,
           uuid_str(channel_id)      AS channel_hex,
           metric,
           scope,
           value,
           uuid_str(pipeline_run_id) AS run_hex
    FROM measurements
    """,
    """
    CREATE VIEW IF NOT EXISTS debug_cell_identities AS
    SELECT uuid_str(id)              AS id_hex,
           uuid_str(origin_fov_id)   AS origin_fov_hex,
           uuid_str(roi_type_id)     AS roi_type_hex,
           created_at
    FROM cell_identities
    """,
    """
    CREATE VIEW IF NOT EXISTS debug_segmentation_sets AS
    SELECT uuid_str(id)                   AS id_hex,
           uuid_str(experiment_id)        AS experiment_hex,
           uuid_str(produces_roi_type_id) AS roi_type_hex,
           seg_type,
           op_config_name,
           source_channel,
           model_name,
           fov_count,
           total_roi_count,
           created_at
    FROM segmentation_sets
    """,
    """
    CREATE VIEW IF NOT EXISTS debug_fov_segmentation_assignments AS
    SELECT uuid_str(id)                   AS id_hex,
           uuid_str(fov_id)               AS fov_hex,
           uuid_str(segmentation_set_id)  AS seg_hex,
           uuid_str(roi_type_id)          AS roi_type_hex,
           is_active,
           uuid_str(pipeline_run_id)      AS run_hex,
           assigned_by,
           assigned_at,
           deactivated_at,
           width,
           height,
           roi_count
    FROM fov_segmentation_assignments
    """,
    """
    CREATE VIEW IF NOT EXISTS debug_fov_mask_assignments AS
    SELECT uuid_str(id)                AS id_hex,
           uuid_str(fov_id)            AS fov_hex,
           uuid_str(threshold_mask_id) AS mask_hex,
           purpose,
           is_active,
           uuid_str(pipeline_run_id)   AS run_hex,
           assigned_by,
           assigned_at,
           deactivated_at
    FROM fov_mask_assignments
    """,
)

# ---------------------------------------------------------------------------
# Connection configuration
# ---------------------------------------------------------------------------


def _configure_connection(conn: sqlite3.Connection) -> None:
    """Apply required PRAGMAs and register UDFs on *conn*.

    Must be called on every ``sqlite3.connect()`` — PRAGMA settings
    are per-connection and not persisted in the database file.

    Args:
        conn: An open SQLite connection.
    """
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-64000")
    conn.row_factory = sqlite3.Row

    # Debug helper — makes UUIDs readable in manual SQL sessions
    conn.create_function(
        "uuid_str",
        1,
        lambda b: str(uuid.UUID(bytes=b)) if b else None,
    )


# ---------------------------------------------------------------------------
# Schema creation
# ---------------------------------------------------------------------------


def create_schema(conn: sqlite3.Connection) -> None:
    """Execute all CREATE TABLE, CREATE INDEX, and CREATE VIEW statements.

    This is idempotent — all DDL uses ``IF NOT EXISTS``.

    Args:
        conn: An open SQLite connection, already configured via
              :func:`_configure_connection`.
    """
    for ddl in _TABLE_DDL:
        conn.execute(ddl)

    for ddl in _INDEX_DDL:
        conn.execute(ddl)

    for ddl in _VIEW_DDL:
        conn.execute(ddl)

    conn.commit()
