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
    percell_version TEXT NOT NULL DEFAULT '4.0.0',
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
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS fovs (
    id INTEGER PRIMARY KEY,
    display_name TEXT NOT NULL UNIQUE,
    condition_id INTEGER NOT NULL REFERENCES conditions(id),
    bio_rep_id INTEGER NOT NULL REFERENCES bio_reps(id),
    timepoint_id INTEGER REFERENCES timepoints(id),
    width INTEGER,
    height INTEGER,
    pixel_size_um REAL,
    source_file TEXT
);

CREATE TABLE IF NOT EXISTS segmentations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    seg_type TEXT NOT NULL DEFAULT 'cellular'
        CHECK(seg_type IN ('whole_field', 'cellular')),
    source_fov_id INTEGER REFERENCES fovs(id) ON DELETE SET NULL,
    source_channel TEXT,
    model_name TEXT NOT NULL DEFAULT '',
    parameters TEXT,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    cell_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS cells (
    id INTEGER PRIMARY KEY,
    fov_id INTEGER NOT NULL REFERENCES fovs(id) ON DELETE CASCADE,
    segmentation_id INTEGER NOT NULL REFERENCES segmentations(id) ON DELETE CASCADE,
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

CREATE TABLE IF NOT EXISTS thresholds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    source_fov_id INTEGER REFERENCES fovs(id) ON DELETE SET NULL,
    source_channel TEXT,
    grouping_channel TEXT,
    method TEXT NOT NULL DEFAULT '',
    parameters TEXT,
    threshold_value REAL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS measurements (
    id INTEGER PRIMARY KEY,
    cell_id INTEGER NOT NULL REFERENCES cells(id) ON DELETE CASCADE,
    channel_id INTEGER NOT NULL REFERENCES channels(id),
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    scope TEXT NOT NULL DEFAULT 'whole_cell'
        CHECK(scope IN ('whole_cell', 'mask_inside', 'mask_outside')),
    segmentation_id INTEGER NOT NULL REFERENCES segmentations(id) ON DELETE CASCADE,
    threshold_id INTEGER REFERENCES thresholds(id) ON DELETE CASCADE,
    measured_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS particles (
    id INTEGER PRIMARY KEY,
    fov_id INTEGER NOT NULL REFERENCES fovs(id) ON DELETE CASCADE,
    threshold_id INTEGER NOT NULL REFERENCES thresholds(id) ON DELETE CASCADE,
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
    UNIQUE(fov_id, threshold_id, label_value)
);

CREATE TABLE IF NOT EXISTS analysis_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS fov_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config_id INTEGER NOT NULL REFERENCES analysis_config(id) ON DELETE CASCADE,
    fov_id INTEGER NOT NULL REFERENCES fovs(id) ON DELETE CASCADE,
    segmentation_id INTEGER NOT NULL REFERENCES segmentations(id) ON DELETE CASCADE,
    threshold_id INTEGER REFERENCES thresholds(id) ON DELETE SET NULL,
    scopes TEXT NOT NULL DEFAULT '["whole_cell"]'
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
    cell_id INTEGER NOT NULL REFERENCES cells(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id),
    PRIMARY KEY (cell_id, tag_id)
);

CREATE TABLE IF NOT EXISTS fov_status_cache (
    fov_id INTEGER PRIMARY KEY REFERENCES fovs(id) ON DELETE CASCADE,
    status_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS fov_tags (
    fov_id INTEGER NOT NULL REFERENCES fovs(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (fov_id, tag_id)
);

-- Partial unique indexes for measurements (handles NULL threshold_id)
CREATE UNIQUE INDEX IF NOT EXISTS idx_meas_unique_with_thresh
    ON measurements(cell_id, channel_id, metric, scope, segmentation_id, threshold_id)
    WHERE threshold_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_meas_unique_without_thresh
    ON measurements(cell_id, channel_id, metric, scope, segmentation_id)
    WHERE threshold_id IS NULL;

-- Partial unique indexes for fov_config (handles NULL threshold_id)
CREATE UNIQUE INDEX IF NOT EXISTS idx_fov_config_with_thresh
    ON fov_config(config_id, fov_id, segmentation_id, threshold_id)
    WHERE threshold_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_fov_config_without_thresh
    ON fov_config(config_id, fov_id, segmentation_id)
    WHERE threshold_id IS NULL;

-- Standard indexes
CREATE INDEX IF NOT EXISTS idx_cells_fov ON cells(fov_id);
CREATE INDEX IF NOT EXISTS idx_cells_fov_valid ON cells(fov_id, is_valid);
CREATE INDEX IF NOT EXISTS idx_cells_segmentation ON cells(segmentation_id);
CREATE INDEX IF NOT EXISTS idx_cells_area ON cells(area_pixels);
CREATE INDEX IF NOT EXISTS idx_measurements_cell ON measurements(cell_id);
CREATE INDEX IF NOT EXISTS idx_measurements_channel ON measurements(channel_id);
CREATE INDEX IF NOT EXISTS idx_measurements_metric ON measurements(metric);
CREATE INDEX IF NOT EXISTS idx_measurements_segmentation ON measurements(segmentation_id);
CREATE INDEX IF NOT EXISTS idx_measurements_threshold ON measurements(threshold_id);
CREATE INDEX IF NOT EXISTS idx_measurements_cell_scope ON measurements(cell_id, scope);
CREATE INDEX IF NOT EXISTS idx_measurements_cell_channel_scope
    ON measurements(cell_id, channel_id, scope);
CREATE INDEX IF NOT EXISTS idx_segmentations_type ON segmentations(seg_type);
CREATE INDEX IF NOT EXISTS idx_segmentations_source_fov ON segmentations(source_fov_id);
CREATE INDEX IF NOT EXISTS idx_thresholds_source_fov ON thresholds(source_fov_id);
CREATE INDEX IF NOT EXISTS idx_fov_config_config ON fov_config(config_id);
CREATE INDEX IF NOT EXISTS idx_fov_config_fov ON fov_config(fov_id);
CREATE INDEX IF NOT EXISTS idx_fov_config_segmentation ON fov_config(segmentation_id);
CREATE INDEX IF NOT EXISTS idx_fovs_condition ON fovs(condition_id);
CREATE INDEX IF NOT EXISTS idx_fovs_bio_rep ON fovs(bio_rep_id);
CREATE INDEX IF NOT EXISTS idx_fov_tags_fov ON fov_tags(fov_id);
CREATE INDEX IF NOT EXISTS idx_fov_tags_tag ON fov_tags(tag_id);
CREATE INDEX IF NOT EXISTS idx_particles_fov ON particles(fov_id);
CREATE INDEX IF NOT EXISTS idx_particles_threshold ON particles(threshold_id);
"""

EXPECTED_TABLES = frozenset({
    "experiments", "channels", "conditions", "timepoints", "bio_reps", "fovs",
    "segmentations", "cells", "measurements", "thresholds",
    "analysis_runs", "tags", "cell_tags", "particles",
    "analysis_config", "fov_config",
    "fov_status_cache", "fov_tags",
})

EXPECTED_INDEXES = frozenset({
    "idx_cells_fov", "idx_cells_fov_valid", "idx_cells_segmentation", "idx_cells_area",
    "idx_measurements_cell", "idx_measurements_channel", "idx_measurements_metric",
    "idx_measurements_segmentation", "idx_measurements_threshold",
    "idx_measurements_cell_scope", "idx_measurements_cell_channel_scope",
    "idx_meas_unique_with_thresh", "idx_meas_unique_without_thresh",
    "idx_segmentations_type", "idx_segmentations_source_fov",
    "idx_thresholds_source_fov",
    "idx_fov_config_config", "idx_fov_config_fov", "idx_fov_config_segmentation",
    "idx_fov_config_with_thresh", "idx_fov_config_without_thresh",
    "idx_fovs_condition", "idx_fovs_bio_rep",
    "idx_fov_tags_fov", "idx_fov_tags_tag",
    "idx_particles_fov", "idx_particles_threshold",
})

EXPECTED_VERSION = "4.0.0"


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


def _ensure_tables(conn: sqlite3.Connection) -> None:
    """Create any missing tables and indexes expected by the current schema.

    Uses CREATE TABLE/INDEX IF NOT EXISTS so it's safe to run on
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

    # Re-run the full schema — IF NOT EXISTS keeps existing tables untouched
    conn.executescript(_SCHEMA_SQL)


def open_database(db_path: Path) -> sqlite3.Connection:
    """Open an existing experiment database.

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        An open connection with WAL mode and foreign keys enabled.

    Raises:
        ExperimentNotFoundError: If the database file does not exist.
        SchemaVersionError: If the schema major version does not match.
    """
    if not db_path.exists():
        raise ExperimentNotFoundError(str(db_path))
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")

    # Check schema version — no migration from older major versions
    row = conn.execute(
        "SELECT percell_version FROM experiments LIMIT 1"
    ).fetchone()
    if row is not None:
        stored = row["percell_version"]
        stored_major = stored.split(".")[0]
        expected_major = EXPECTED_VERSION.split(".")[0]
        if stored_major != expected_major:
            conn.close()
            raise SchemaVersionError(stored, EXPECTED_VERSION)

    # Ensure all expected tables exist (handles partially migrated databases)
    _ensure_tables(conn)

    return conn
