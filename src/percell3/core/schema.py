"""SQLite schema creation and database opening for PerCell 3."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from percell3.core.exceptions import ExperimentNotFoundError, SchemaVersionError

_SCHEMA_SQL = """\
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS experiments (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    percell_version TEXT NOT NULL DEFAULT '3.3.0',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS channels (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    role TEXT,
    excitation_nm REAL,
    emission_nm REAL,
    color TEXT,
    is_segmentation INTEGER NOT NULL DEFAULT 0,
    display_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS conditions (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS timepoints (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    time_seconds REAL,
    display_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS bio_reps (
    id INTEGER PRIMARY KEY,
    condition_id INTEGER NOT NULL REFERENCES conditions(id),
    name TEXT NOT NULL DEFAULT 'N1',
    UNIQUE(condition_id, name)
);

CREATE TABLE IF NOT EXISTS fovs (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    bio_rep_id INTEGER NOT NULL REFERENCES bio_reps(id),
    timepoint_id INTEGER REFERENCES timepoints(id),
    width INTEGER,
    height INTEGER,
    pixel_size_um REAL,
    source_file TEXT,
    UNIQUE(name, bio_rep_id, timepoint_id)
);

CREATE TABLE IF NOT EXISTS segmentation_runs (
    id INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL REFERENCES channels(id),
    model_name TEXT NOT NULL,
    parameters TEXT,
    cell_count INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS cells (
    id INTEGER PRIMARY KEY,
    fov_id INTEGER NOT NULL REFERENCES fovs(id),
    segmentation_id INTEGER NOT NULL REFERENCES segmentation_runs(id),
    label_value INTEGER NOT NULL,
    centroid_x REAL NOT NULL,
    centroid_y REAL NOT NULL,
    bbox_x INTEGER NOT NULL,
    bbox_y INTEGER NOT NULL,
    bbox_w INTEGER NOT NULL,
    bbox_h INTEGER NOT NULL,
    area_pixels REAL NOT NULL,
    area_um2 REAL,
    perimeter REAL,
    circularity REAL,
    is_valid INTEGER NOT NULL DEFAULT 1,
    UNIQUE(fov_id, segmentation_id, label_value)
);

CREATE TABLE IF NOT EXISTS measurements (
    id INTEGER PRIMARY KEY,
    cell_id INTEGER NOT NULL REFERENCES cells(id),
    channel_id INTEGER NOT NULL REFERENCES channels(id),
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    scope TEXT NOT NULL DEFAULT 'whole_cell',
    threshold_run_id INTEGER REFERENCES threshold_runs(id),
    UNIQUE(cell_id, channel_id, metric, scope),
    CHECK(scope IN ('whole_cell', 'mask_inside', 'mask_outside'))
);

CREATE TABLE IF NOT EXISTS threshold_runs (
    id INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL REFERENCES channels(id),
    method TEXT NOT NULL,
    parameters TEXT,
    threshold_value REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id INTEGER PRIMARY KEY,
    plugin_name TEXT NOT NULL,
    parameters TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    cell_count INTEGER,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    color TEXT
);

CREATE TABLE IF NOT EXISTS cell_tags (
    cell_id INTEGER NOT NULL REFERENCES cells(id),
    tag_id INTEGER NOT NULL REFERENCES tags(id),
    PRIMARY KEY (cell_id, tag_id)
);

CREATE INDEX IF NOT EXISTS idx_cells_fov ON cells(fov_id);
CREATE INDEX IF NOT EXISTS idx_cells_fov_valid ON cells(fov_id, is_valid);
CREATE INDEX IF NOT EXISTS idx_cells_segmentation ON cells(segmentation_id);
CREATE INDEX IF NOT EXISTS idx_cells_area ON cells(area_pixels);
CREATE INDEX IF NOT EXISTS idx_measurements_cell ON measurements(cell_id);
CREATE INDEX IF NOT EXISTS idx_measurements_channel ON measurements(channel_id);
CREATE INDEX IF NOT EXISTS idx_measurements_metric ON measurements(metric);
CREATE TABLE IF NOT EXISTS particles (
    id INTEGER PRIMARY KEY,
    cell_id INTEGER NOT NULL REFERENCES cells(id),
    threshold_run_id INTEGER NOT NULL REFERENCES threshold_runs(id),
    label_value INTEGER NOT NULL,
    centroid_x REAL NOT NULL,
    centroid_y REAL NOT NULL,
    bbox_x INTEGER NOT NULL,
    bbox_y INTEGER NOT NULL,
    bbox_w INTEGER NOT NULL,
    bbox_h INTEGER NOT NULL,
    area_pixels REAL NOT NULL,
    area_um2 REAL,
    perimeter REAL,
    circularity REAL,
    eccentricity REAL,
    solidity REAL,
    major_axis_length REAL,
    minor_axis_length REAL,
    mean_intensity REAL,
    max_intensity REAL,
    integrated_intensity REAL,
    UNIQUE(cell_id, threshold_run_id, label_value)
);

CREATE INDEX IF NOT EXISTS idx_bio_reps_condition ON bio_reps(condition_id);
CREATE INDEX IF NOT EXISTS idx_fovs_bio_rep ON fovs(bio_rep_id);
CREATE INDEX IF NOT EXISTS idx_particles_cell ON particles(cell_id);
CREATE INDEX IF NOT EXISTS idx_particles_run ON particles(threshold_run_id);
"""

EXPECTED_TABLES = frozenset({
    "experiments", "channels", "conditions", "timepoints", "bio_reps", "fovs",
    "segmentation_runs", "cells", "measurements", "threshold_runs",
    "analysis_runs", "tags", "cell_tags", "particles",
})

EXPECTED_INDEXES = frozenset({
    "idx_cells_fov", "idx_cells_fov_valid", "idx_cells_segmentation", "idx_cells_area",
    "idx_measurements_cell", "idx_measurements_channel", "idx_measurements_metric",
    "idx_bio_reps_condition", "idx_fovs_bio_rep",
    "idx_particles_cell", "idx_particles_run",
})

EXPECTED_VERSION = "3.3.0"


def create_schema(
    db_path: Path,
    name: str = "",
    description: str = "",
) -> sqlite3.Connection:
    """Create a new experiment database with the full schema.

    Args:
        db_path: Path to the SQLite database file (will be created).
        name: Experiment name.
        description: Experiment description.

    Returns:
        An open connection to the new database.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA_SQL)
    conn.execute(
        "INSERT INTO experiments (name, description, percell_version) VALUES (?, ?, ?)",
        (name, description, EXPECTED_VERSION),
    )
    conn.commit()
    return conn


def _migrate_3_2_to_3_3(conn: sqlite3.Connection) -> None:
    """Migrate schema from 3.2.0 to 3.3.0.

    Changes:
    - Adds scope and threshold_run_id to measurements (temp table swap).
    - Creates particles table and indexes if missing from older databases.
    """
    conn.executescript("""
        -- Measurements: add scope + threshold_run_id, update unique constraint
        CREATE TABLE measurements_new (
            id INTEGER PRIMARY KEY,
            cell_id INTEGER NOT NULL REFERENCES cells(id),
            channel_id INTEGER NOT NULL REFERENCES channels(id),
            metric TEXT NOT NULL,
            value REAL NOT NULL,
            scope TEXT NOT NULL DEFAULT 'whole_cell',
            threshold_run_id INTEGER REFERENCES threshold_runs(id),
            UNIQUE(cell_id, channel_id, metric, scope),
            CHECK(scope IN ('whole_cell', 'mask_inside', 'mask_outside'))
        );

        INSERT INTO measurements_new (id, cell_id, channel_id, metric, value, scope)
            SELECT id, cell_id, channel_id, metric, value, 'whole_cell'
            FROM measurements;

        DROP TABLE measurements;
        ALTER TABLE measurements_new RENAME TO measurements;

        CREATE INDEX IF NOT EXISTS idx_measurements_cell ON measurements(cell_id);
        CREATE INDEX IF NOT EXISTS idx_measurements_channel ON measurements(channel_id);
        CREATE INDEX IF NOT EXISTS idx_measurements_metric ON measurements(metric);

        -- Particles table (may be missing from older 3.2 databases)
        CREATE TABLE IF NOT EXISTS particles (
            id INTEGER PRIMARY KEY,
            cell_id INTEGER NOT NULL REFERENCES cells(id),
            threshold_run_id INTEGER NOT NULL REFERENCES threshold_runs(id),
            label_value INTEGER NOT NULL,
            centroid_x REAL NOT NULL,
            centroid_y REAL NOT NULL,
            bbox_x INTEGER NOT NULL,
            bbox_y INTEGER NOT NULL,
            bbox_w INTEGER NOT NULL,
            bbox_h INTEGER NOT NULL,
            area_pixels REAL NOT NULL,
            area_um2 REAL,
            perimeter REAL,
            circularity REAL,
            eccentricity REAL,
            solidity REAL,
            major_axis_length REAL,
            minor_axis_length REAL,
            mean_intensity REAL,
            max_intensity REAL,
            integrated_intensity REAL,
            UNIQUE(cell_id, threshold_run_id, label_value)
        );

        CREATE INDEX IF NOT EXISTS idx_bio_reps_condition ON bio_reps(condition_id);
        CREATE INDEX IF NOT EXISTS idx_fovs_bio_rep ON fovs(bio_rep_id);
        CREATE INDEX IF NOT EXISTS idx_particles_cell ON particles(cell_id);
        CREATE INDEX IF NOT EXISTS idx_particles_run ON particles(threshold_run_id);

        UPDATE experiments SET percell_version = '3.3.0';
    """)


def _ensure_tables(conn: sqlite3.Connection) -> None:
    """Create any missing tables and indexes expected by the current schema.

    This handles databases that were partially migrated or created by older
    code that didn't have all tables (e.g., particles added after initial
    schema).  Uses CREATE TABLE/INDEX IF NOT EXISTS so it's safe to run on
    complete databases.
    """
    existing = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    missing = EXPECTED_TABLES - existing
    if not missing:
        return

    # Only create tables that are missing — use IF NOT EXISTS for safety
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS particles (
            id INTEGER PRIMARY KEY,
            cell_id INTEGER NOT NULL REFERENCES cells(id),
            threshold_run_id INTEGER NOT NULL REFERENCES threshold_runs(id),
            label_value INTEGER NOT NULL,
            centroid_x REAL NOT NULL,
            centroid_y REAL NOT NULL,
            bbox_x INTEGER NOT NULL,
            bbox_y INTEGER NOT NULL,
            bbox_w INTEGER NOT NULL,
            bbox_h INTEGER NOT NULL,
            area_pixels REAL NOT NULL,
            area_um2 REAL,
            perimeter REAL,
            circularity REAL,
            eccentricity REAL,
            solidity REAL,
            major_axis_length REAL,
            minor_axis_length REAL,
            mean_intensity REAL,
            max_intensity REAL,
            integrated_intensity REAL,
            UNIQUE(cell_id, threshold_run_id, label_value)
        );

        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            color TEXT
        );

        CREATE TABLE IF NOT EXISTS cell_tags (
            cell_id INTEGER NOT NULL REFERENCES cells(id),
            tag_id INTEGER NOT NULL REFERENCES tags(id),
            PRIMARY KEY (cell_id, tag_id)
        );

        CREATE TABLE IF NOT EXISTS analysis_runs (
            id INTEGER PRIMARY KEY,
            plugin_name TEXT NOT NULL,
            parameters TEXT,
            status TEXT NOT NULL DEFAULT 'running',
            cell_count INTEGER,
            started_at TEXT NOT NULL DEFAULT (datetime('now')),
            completed_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_particles_cell ON particles(cell_id);
        CREATE INDEX IF NOT EXISTS idx_particles_run ON particles(threshold_run_id);
        CREATE INDEX IF NOT EXISTS idx_bio_reps_condition ON bio_reps(condition_id);
        CREATE INDEX IF NOT EXISTS idx_fovs_bio_rep ON fovs(bio_rep_id);
    """)


def open_database(db_path: Path) -> sqlite3.Connection:
    """Open an existing experiment database.

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        An open connection with WAL mode and foreign keys enabled.

    Raises:
        ExperimentNotFoundError: If the database file does not exist.
    """
    if not db_path.exists():
        raise ExperimentNotFoundError(str(db_path))
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")

    # Check schema version and auto-migrate if possible
    row = conn.execute(
        "SELECT percell_version FROM experiments LIMIT 1"
    ).fetchone()
    if row is not None:
        stored = row["percell_version"]
        stored_parts = stored.split(".")[:2]
        expected_parts = EXPECTED_VERSION.split(".")[:2]
        if stored_parts != expected_parts:
            # Try auto-migration
            if stored_parts == ["3", "2"]:
                _migrate_3_2_to_3_3(conn)
            else:
                conn.close()
                raise SchemaVersionError(stored, EXPECTED_VERSION)

    # Ensure all expected tables exist (handles partially migrated databases)
    _ensure_tables(conn)

    return conn
