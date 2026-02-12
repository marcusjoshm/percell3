# PerCell 3 — Data Model

## The .percell Directory

Each experiment produces a single self-contained directory:

```
my_experiment.percell/
├── experiment.db                    # SQLite: all metadata + measurements
├── images.zarr/                     # OME-Zarr: raw image data
│   ├── condition_1/
│   │   └── region_1/               # One OME-Zarr group per FOV
│   │       ├── 0/                   # Resolution level 0 (full res)
│   │       ├── 1/                   # Resolution level 1 (2x downsample)
│   │       └── .zattrs              # OME-NGFF metadata (channels, scales)
│   └── ...
├── labels.zarr/                     # OME-Zarr: segmentation labels
│   └── condition_1/region_1/        # Integer-coded label image
├── masks.zarr/                      # OME-Zarr: analysis masks
│   └── condition_1/region_1/
│       ├── threshold_GFP/           # Binary mask from GFP thresholding
│       └── threshold_RFP/
└── exports/                         # User-requested CSV/TIFF exports
```

## Entity Relationships

```
Experiment (1)
  ├── has many Channels
  ├── has many Conditions
  │     └── has many Regions (FOVs)
  │           ├── has one multi-channel Image (in images.zarr)
  │           ├── has many Label Images (in labels.zarr, one per segmentation run)
  │           └── has many Masks (in masks.zarr, one per threshold run)
  ├── has many Segmentation Runs
  │     └── produces Cells (label_value, bbox, area, centroid)
  ├── has many Cells
  │     ├── has many Measurements (cell_id x channel x metric -> value)
  │     └── has many Tags
  ├── has many Threshold Runs
  └── has many Analysis Runs (plugin executions)
```

## SQLite Schema Summary

### Tables

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `experiments` | Experiment metadata | name, description, created_at |
| `channels` | Imaging channels | name, role, excitation_nm, emission_nm, color |
| `conditions` | Experimental conditions | name, description |
| `timepoints` | Time series points | name, time_seconds |
| `regions` | Fields of view | name, condition_id, timepoint_id, width, height, pixel_size_um |
| `segmentation_runs` | Segmentation history | channel_id, model_name, parameters (JSON) |
| `cells` | Individual cell records | region_id, segmentation_id, label_value, centroid, bbox, area |
| `measurements` | Per-cell measurements | cell_id, channel_id, metric, value |
| `threshold_runs` | Thresholding history | channel_id, method, parameters (JSON) |
| `analysis_runs` | Plugin execution history | plugin_name, parameters, status, started_at |
| `tags` | Cell classification labels | name, color |
| `cell_tags` | Cell-to-tag junction | cell_id, tag_id |

### Key Constraints
- All IDs are INTEGER PRIMARY KEY (SQLite rowid aliases)
- Foreign keys enforced (`PRAGMA foreign_keys = ON`)
- WAL mode for concurrent read safety (`PRAGMA journal_mode = WAL`)
- Unique constraints on: channel names, condition names, region names within conditions
- Measurements have a unique constraint on (cell_id, channel_id, metric)

## Data Flow

```
1. Import:    LIF/TIFF/CZI  -->  images.zarr + channels/conditions/regions in SQLite
2. Segment:   images.zarr    -->  labels.zarr + cells table in SQLite
3. Measure:   images.zarr + labels.zarr  -->  measurements table in SQLite
4. Threshold: images.zarr    -->  masks.zarr + threshold_runs in SQLite
5. Plugin:    ExperimentStore -->  measurements + optional Zarr layers
6. Export:    SQLite          -->  CSV files in exports/
```
