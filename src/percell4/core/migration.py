"""Schema migration runner for .percell databases.

Supports forward migration from older schema versions to the current
version.  Each migration is a function that receives an open connection
and applies ALTER TABLE / CREATE TABLE / data backfill statements.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

MIGRATIONS: dict[str, list[str]] = {
    "5.0.0->5.1.0": [
        "ALTER TABLE fovs ADD COLUMN pixel_size_um REAL",
        "UPDATE experiments SET schema_version = '5.1.0' WHERE 1=1",
    ],
}

SCHEMA_VERSION = "6.0.0"


def get_schema_version(conn: sqlite3.Connection) -> str:
    """Read current schema version from database.

    The version is stored in the ``experiments`` table's
    ``schema_version`` column (single-experiment-per-DB convention).
    """
    row = conn.execute(
        "SELECT schema_version FROM experiments LIMIT 1"
    ).fetchone()
    if row is None:
        return "unknown"
    # Support both dict-like Row and plain tuple
    try:
        return row["schema_version"]
    except (TypeError, IndexError):
        return row[0]


def _backup_database(db_path: Path) -> Path:
    """Create a backup copy of the database file before migration.

    Args:
        db_path: Path to the database file.

    Returns:
        Path to the backup file.
    """
    backup_path = db_path.with_suffix(".db.pre_migration_backup")
    shutil.copy2(str(db_path), str(backup_path))
    logger.info("Database backed up to %s", backup_path)
    return backup_path


def _migrate_5_1_0_to_6_0_0(conn: sqlite3.Connection) -> None:
    """Migrate schema from 5.1.0 to 6.0.0.

    Changes:
    - Add display_name, pipeline_run_id, lineage_depth, lineage_path,
      channel_metadata columns to fovs
    - Recreate measurements table to make value nullable (REAL, not REAL NOT NULL)
    - Recreate cell_identities with ON DELETE RESTRICT on origin_fov_id
    - Recreate rois with ON DELETE CASCADE on fov_id
    - Recreate fov_status_log with ON DELETE CASCADE on fov_id
    - Add idx_fovs_lineage_path index
    - Backfill lineage_depth and lineage_path for existing FOVs
    - Update schema_version to 6.0.0
    """
    # -- 1. Add new columns to fovs --
    # SQLite ALTER TABLE ADD COLUMN is safe for nullable/default columns
    for alter_sql in [
        "ALTER TABLE fovs ADD COLUMN display_name TEXT",
        "ALTER TABLE fovs ADD COLUMN pipeline_run_id BLOB(16) "
        "REFERENCES pipeline_runs CHECK(pipeline_run_id IS NULL OR length(pipeline_run_id) = 16)",
        "ALTER TABLE fovs ADD COLUMN lineage_depth INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE fovs ADD COLUMN lineage_path TEXT",
        "ALTER TABLE fovs ADD COLUMN channel_metadata TEXT "
        "CHECK(channel_metadata IS NULL OR json_valid(channel_metadata))",
    ]:
        try:
            conn.execute(alter_sql)
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise

    # -- 2. Recreate measurements table (value REAL NOT NULL -> REAL) --
    conn.execute("""
        CREATE TABLE IF NOT EXISTS measurements_new (
            id              BLOB(16) PRIMARY KEY CHECK(length(id) = 16),
            roi_id          BLOB(16) NOT NULL REFERENCES rois
                                ON DELETE CASCADE
                                CHECK(length(roi_id) = 16),
            channel_id      BLOB(16) NOT NULL REFERENCES channels
                                CHECK(length(channel_id) = 16),
            metric          TEXT NOT NULL,
            scope           TEXT NOT NULL
                                CHECK(scope IN (
                                    'whole_roi', 'mask_inside', 'mask_outside'
                                )),
            value           REAL,
            pipeline_run_id BLOB(16) NOT NULL REFERENCES pipeline_runs
                                CHECK(length(pipeline_run_id) = 16)
        )
    """)
    conn.execute("""
        INSERT INTO measurements_new
            (id, roi_id, channel_id, metric, scope, value, pipeline_run_id)
        SELECT id, roi_id, channel_id, metric, scope, value, pipeline_run_id
        FROM measurements
    """)
    conn.execute("DROP TABLE measurements")
    conn.execute("ALTER TABLE measurements_new RENAME TO measurements")

    # Recreate measurement indexes
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_measurements_roi_channel_scope
            ON measurements(roi_id, channel_id, scope)
    """)
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_measurements_unique_per_run
            ON measurements(roi_id, channel_id, metric, scope, pipeline_run_id)
    """)

    # -- 3. Recreate cell_identities with ON DELETE RESTRICT --
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cell_identities_new (
            id              BLOB(16) PRIMARY KEY CHECK(length(id) = 16),
            origin_fov_id   BLOB(16) NOT NULL REFERENCES fovs
                                ON DELETE RESTRICT
                                CHECK(length(origin_fov_id) = 16),
            roi_type_id     BLOB(16) NOT NULL REFERENCES roi_type_definitions
                                CHECK(length(roi_type_id) = 16),
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        INSERT INTO cell_identities_new (id, origin_fov_id, roi_type_id, created_at)
        SELECT id, origin_fov_id, roi_type_id, created_at
        FROM cell_identities
    """)
    conn.execute("DROP TABLE cell_identities")
    conn.execute("ALTER TABLE cell_identities_new RENAME TO cell_identities")

    # -- 4. Recreate rois with ON DELETE CASCADE on fov_id --
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rois_new (
            id                  BLOB(16) PRIMARY KEY CHECK(length(id) = 16),
            fov_id              BLOB(16) NOT NULL REFERENCES fovs
                                    ON DELETE CASCADE
                                    CHECK(length(fov_id) = 16),
            roi_type_id         BLOB(16) NOT NULL REFERENCES roi_type_definitions
                                    CHECK(length(roi_type_id) = 16),
            cell_identity_id    BLOB(16) REFERENCES cell_identities
                                    CHECK(cell_identity_id IS NULL
                                          OR length(cell_identity_id) = 16),
            parent_roi_id       BLOB(16) REFERENCES rois_new
                                    CHECK(parent_roi_id IS NULL
                                          OR length(parent_roi_id) = 16),
            label_id            INTEGER NOT NULL,
            bbox_y              INTEGER NOT NULL,
            bbox_x              INTEGER NOT NULL,
            bbox_h              INTEGER NOT NULL,
            bbox_w              INTEGER NOT NULL,
            area_px             INTEGER NOT NULL
        )
    """)
    conn.execute("""
        INSERT INTO rois_new
            (id, fov_id, roi_type_id, cell_identity_id, parent_roi_id,
             label_id, bbox_y, bbox_x, bbox_h, bbox_w, area_px)
        SELECT id, fov_id, roi_type_id, cell_identity_id, parent_roi_id,
               label_id, bbox_y, bbox_x, bbox_h, bbox_w, area_px
        FROM rois
    """)
    conn.execute("DROP TABLE rois")
    conn.execute("ALTER TABLE rois_new RENAME TO rois")

    # Recreate ROI indexes
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_roi_identity_fov
            ON rois(cell_identity_id, fov_id)
            WHERE cell_identity_id IS NOT NULL
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_rois_fov
            ON rois(fov_id)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_rois_type
            ON rois(roi_type_id)
    """)

    # -- 5. Recreate fov_status_log with ON DELETE CASCADE --
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fov_status_log_new (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            fov_id      BLOB(16) NOT NULL REFERENCES fovs
                            ON DELETE CASCADE
                            CHECK(length(fov_id) = 16),
            old_status  TEXT,
            new_status  TEXT NOT NULL,
            message     TEXT,
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        INSERT INTO fov_status_log_new (id, fov_id, old_status, new_status, message, created_at)
        SELECT id, fov_id, old_status, new_status, message, created_at
        FROM fov_status_log
    """)
    conn.execute("DROP TABLE fov_status_log")
    conn.execute("ALTER TABLE fov_status_log_new RENAME TO fov_status_log")

    # -- 6. Add lineage_path index --
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_fovs_lineage_path
            ON fovs(lineage_path)
            WHERE lineage_path IS NOT NULL
    """)

    # -- 7. Backfill lineage_depth and lineage_path for existing FOVs --
    # Root FOVs (no parent): depth=0, path=/<hex(id)>
    conn.execute("""
        UPDATE fovs
        SET lineage_depth = 0,
            lineage_path = '/' || hex(id)
        WHERE parent_fov_id IS NULL
          AND lineage_path IS NULL
    """)

    # Derived FOVs: iteratively build from parent paths
    # We iterate up to a reasonable depth limit
    for _ in range(50):
        updated = conn.execute("""
            UPDATE fovs
            SET lineage_depth = (
                    SELECT p.lineage_depth + 1
                    FROM fovs p WHERE p.id = fovs.parent_fov_id
                ),
                lineage_path = (
                    SELECT p.lineage_path || '/' || hex(fovs.id)
                    FROM fovs p WHERE p.id = fovs.parent_fov_id
                )
            WHERE parent_fov_id IS NOT NULL
              AND lineage_path IS NULL
              AND parent_fov_id IN (
                  SELECT id FROM fovs WHERE lineage_path IS NOT NULL
              )
        """).rowcount
        if updated == 0:
            break

    # -- 8. Create workflow_configs table if not exists --
    conn.execute("""
        CREATE TABLE IF NOT EXISTS workflow_configs (
            id              BLOB(16) PRIMARY KEY CHECK(length(id) = 16),
            workflow_name   TEXT NOT NULL,
            config_name     TEXT NOT NULL,
            config_json     TEXT NOT NULL CHECK(json_valid(config_json)),
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(workflow_name, config_name)
        )
    """)

    # -- 9. Update schema version --
    conn.execute("UPDATE experiments SET schema_version = '6.0.0' WHERE 1=1")


def run_migrations(
    conn: sqlite3.Connection, current: str, target: str
) -> list[str]:
    """Apply migrations from *current* to *target* version.

    Returns list of applied migration keys.
    """
    applied: list[str] = []

    # Handle simple SQL-only migrations first
    for key, statements in MIGRATIONS.items():
        from_ver, to_ver = key.split("->")
        if from_ver == current:
            for sql in statements:
                conn.execute(sql)
            applied.append(key)
            current = to_ver
            if current == target:
                break

    # Handle 5.1.0 -> 6.0.0 migration (requires Python logic)
    if current == "5.1.0" and target == "6.0.0":
        _migrate_5_1_0_to_6_0_0(conn)
        applied.append("5.1.0->6.0.0")
        current = "6.0.0"

    return applied


def migrate_database(
    db_path: Path,
    conn: sqlite3.Connection,
    *,
    target_version: str = SCHEMA_VERSION,
) -> list[str]:
    """Migrate database to target version with backup and safety checks.

    Creates a backup of the database file before migrating, wraps the
    migration in a transaction, and runs PRAGMA foreign_key_check
    post-migration.

    Args:
        db_path: Path to the database file (for backup).
        conn: Open connection to the database.
        target_version: Version to migrate to (default: current SCHEMA_VERSION).

    Returns:
        List of applied migration keys.

    Raises:
        RuntimeError: If foreign key check fails post-migration.
    """
    current = get_schema_version(conn)
    if current == target_version:
        return []

    # Backup before migration
    if db_path.exists() and str(db_path) != ":memory:":
        backup_path = _backup_database(db_path)
    else:
        backup_path = None

    try:
        # Disable FK enforcement during migration (table recreation)
        conn.execute("PRAGMA foreign_keys=OFF")

        # Run migration in explicit transaction
        conn.execute("BEGIN IMMEDIATE")
        try:
            applied = run_migrations(conn, current, target_version)

            # Post-migration foreign key integrity check
            fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            if fk_violations:
                conn.execute("ROLLBACK")
                raise RuntimeError(
                    f"Foreign key check failed after migration: "
                    f"{len(fk_violations)} violations found"
                )

            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.OperationalError:
                pass  # Already rolled back
            raise
        finally:
            # Re-enable FK enforcement
            conn.execute("PRAGMA foreign_keys=ON")

        logger.info(
            "Database migrated from %s to %s (applied: %s)",
            current, target_version, applied,
        )
        return applied

    except Exception:
        # Restore from backup on failure
        if backup_path and backup_path.exists():
            logger.error(
                "Migration failed, backup available at %s", backup_path
            )
        raise
