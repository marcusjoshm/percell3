-- PerCell 3 SQLite Schema
-- This schema is created by percell3.core.schema.create_schema()

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- Experiment metadata (singleton row)
CREATE TABLE IF NOT EXISTS experiments (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    percell_version TEXT NOT NULL DEFAULT '3.0.0',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Imaging channels
CREATE TABLE IF NOT EXISTS channels (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    role TEXT,                           -- 'nucleus', 'signal', 'membrane', etc.
    excitation_nm REAL,
    emission_nm REAL,
    color TEXT,                          -- hex color '#0000FF'
    is_segmentation INTEGER NOT NULL DEFAULT 0,
    display_order INTEGER NOT NULL DEFAULT 0
);

-- Experimental conditions
CREATE TABLE IF NOT EXISTS conditions (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT ''
);

-- Timepoints (for timelapse experiments)
CREATE TABLE IF NOT EXISTS timepoints (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    time_seconds REAL,
    display_order INTEGER NOT NULL DEFAULT 0
);

-- Regions (fields of view / technical replicates)
CREATE TABLE IF NOT EXISTS regions (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    condition_id INTEGER NOT NULL REFERENCES conditions(id),
    timepoint_id INTEGER REFERENCES timepoints(id),
    width INTEGER,
    height INTEGER,
    pixel_size_um REAL,
    source_file TEXT,                    -- original filename for provenance
    zarr_path TEXT,                      -- relative path within images.zarr
    UNIQUE(name, condition_id, timepoint_id)
);

-- Segmentation runs (history of what was run)
CREATE TABLE IF NOT EXISTS segmentation_runs (
    id INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL REFERENCES channels(id),
    model_name TEXT NOT NULL,            -- 'cyto3', 'nuclei', custom model path
    parameters TEXT,                     -- JSON blob of cellpose parameters
    cell_count INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Individual cells
CREATE TABLE IF NOT EXISTS cells (
    id INTEGER PRIMARY KEY,
    region_id INTEGER NOT NULL REFERENCES regions(id),
    segmentation_id INTEGER NOT NULL REFERENCES segmentation_runs(id),
    label_value INTEGER NOT NULL,        -- pixel value in label image
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
    is_valid INTEGER NOT NULL DEFAULT 1, -- for soft-delete / filtering
    UNIQUE(region_id, segmentation_id, label_value)
);

-- Per-cell measurements
CREATE TABLE IF NOT EXISTS measurements (
    id INTEGER PRIMARY KEY,
    cell_id INTEGER NOT NULL REFERENCES cells(id),
    channel_id INTEGER NOT NULL REFERENCES channels(id),
    metric TEXT NOT NULL,                -- 'mean_intensity', 'max_intensity', etc.
    value REAL NOT NULL,
    UNIQUE(cell_id, channel_id, metric)
);

-- Threshold runs
CREATE TABLE IF NOT EXISTS threshold_runs (
    id INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL REFERENCES channels(id),
    method TEXT NOT NULL,                -- 'otsu', 'adaptive', 'manual'
    parameters TEXT,                     -- JSON blob
    threshold_value REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Analysis/plugin runs
CREATE TABLE IF NOT EXISTS analysis_runs (
    id INTEGER PRIMARY KEY,
    plugin_name TEXT NOT NULL,
    parameters TEXT,                     -- JSON blob
    status TEXT NOT NULL DEFAULT 'running',  -- 'running', 'completed', 'failed'
    cell_count INTEGER,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT
);

-- Tags for cell classification
CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    color TEXT                           -- hex color for display
);

-- Cell-to-tag junction table
CREATE TABLE IF NOT EXISTS cell_tags (
    cell_id INTEGER NOT NULL REFERENCES cells(id),
    tag_id INTEGER NOT NULL REFERENCES tags(id),
    PRIMARY KEY (cell_id, tag_id)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_cells_region ON cells(region_id);
CREATE INDEX IF NOT EXISTS idx_cells_segmentation ON cells(segmentation_id);
CREATE INDEX IF NOT EXISTS idx_cells_area ON cells(area_pixels);
CREATE INDEX IF NOT EXISTS idx_measurements_cell ON measurements(cell_id);
CREATE INDEX IF NOT EXISTS idx_measurements_channel ON measurements(channel_id);
CREATE INDEX IF NOT EXISTS idx_measurements_metric ON measurements(metric);
CREATE INDEX IF NOT EXISTS idx_regions_condition ON regions(condition_id);
