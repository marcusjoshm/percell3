"""SQLite schema creation and database opening for PerCell 3."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from percell3.core.exceptions import ExperimentNotFoundError

_SCHEMA_SQL = """\
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS experiments (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    percell_version TEXT NOT NULL DEFAULT '3.0.0',
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

CREATE TABLE IF NOT EXISTS fovs (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    condition_id INTEGER NOT NULL REFERENCES conditions(id),
    timepoint_id INTEGER REFERENCES timepoints(id),
    width INTEGER,
    height INTEGER,
    pixel_size_um REAL,
    source_file TEXT,
    zarr_path TEXT,
    UNIQUE(name, condition_id, timepoint_id)
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
    UNIQUE(cell_id, channel_id, metric)
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
CREATE INDEX IF NOT EXISTS idx_cells_segmentation ON cells(segmentation_id);
CREATE INDEX IF NOT EXISTS idx_cells_area ON cells(area_pixels);
CREATE INDEX IF NOT EXISTS idx_measurements_cell ON measurements(cell_id);
CREATE INDEX IF NOT EXISTS idx_measurements_channel ON measurements(channel_id);
CREATE INDEX IF NOT EXISTS idx_measurements_metric ON measurements(metric);
CREATE INDEX IF NOT EXISTS idx_fovs_condition ON fovs(condition_id);
"""

EXPECTED_TABLES = frozenset({
    "experiments", "channels", "conditions", "timepoints", "fovs",
    "segmentation_runs", "cells", "measurements", "threshold_runs",
    "analysis_runs", "tags", "cell_tags",
})

EXPECTED_INDEXES = frozenset({
    "idx_cells_fov", "idx_cells_segmentation", "idx_cells_area",
    "idx_measurements_cell", "idx_measurements_channel", "idx_measurements_metric",
    "idx_fovs_condition",
})


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
        "INSERT INTO experiments (name, description) VALUES (?, ?)",
        (name, description),
    )
    conn.commit()
    return conn


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
    return conn
