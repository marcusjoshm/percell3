# PerCell Architecture: P-body Workflow Use Case
*Concrete architecture recommendations based on two-channel P-body sensor analysis workflow*

---

## Workflow Summary

1. Import 2-channel FOVs
2. Cellpose segmentation on Channel 1
3. Napari QC — delete and redraw bad cells
4. Select conditions to analyze
5. **Round 1 threshold** → dilate binary mask → create **Derived FOV 1** (mask-subtracted)
6. **Round 2 segmentation** on Derived FOV 1 → create **Derived FOV 2** (particle candidates)
7. **Background estimation** from Derived FOV 2 → **background subtraction** per cell → create **Derived FOV 3**
8. **Final measurements** on Derived FOV 3, using Round 1 threshold mask
9. Export filtered results by condition, group, channel, metric

---

## Hard Architectural Requirements

| Requirement | Why |
|---|---|
| **FOV Lineage Tree** | FOVs form a derivation chain, not a flat list. Every derived FOV must know its parent and the operation that created it. |
| **Persistent Cell Identity Across Derived Images** | Cell #47 in the original FOV is the same physical cell in every downstream derived image. Stable identity must survive the derivation tree. |
| **Particles Are Children of Cells** | Round 2 segmentation produces sub-ROIs (P-body candidates) spatially owned by parent cells from the original segmentation — across different FOVs. |
| **Intensity Groups Are First-Class Query Objects** | Must support "give me cells in group 2 only" or "exclude group 0" at query time, not just as post-hoc filters. |
| **Analysis Status Per FOV** | Need at-a-glance view of what's analyzed, QC'd, pending, or errored. |
| **Workflow Config Defines Derivation Graph** | Config isn't just parameters — it defines the pipeline topology that produces derived FOVs. |

---

## Database: SQLite (Structured Correctly)

**Keep SQLite** — DuckDB is overkill unless routinely working with millions of cells across thousands of FOVs. SQLite in WAL mode with proper indexes handles this workflow. The key is schema design, not engine.

---

### FOV Lineage Table

```sql
CREATE TABLE fovs (
    id               TEXT PRIMARY KEY,  -- UUID
    experiment_id    TEXT REFERENCES experiments(id),
    condition_id     TEXT REFERENCES conditions(id),
    bio_rep_id       TEXT REFERENCES bio_reps(id),

    -- Identity
    display_name     TEXT NOT NULL,   -- e.g. "ctrl_N1_001"
    auto_name        TEXT NOT NULL,   -- e.g. "ctrl_N1_001_msksubt_bgsub"
    fov_index        INTEGER,

    -- Lineage
    parent_fov_id    TEXT REFERENCES fovs(id),   -- NULL = original
    derivation_op    TEXT,    -- 'mask_subtract' | 'background_subtract' | 'resegment'
    derivation_params TEXT,   -- JSON: exact params used
    pipeline_run_id  TEXT REFERENCES pipeline_runs(id),
    lineage_depth    INTEGER DEFAULT 0,  -- 0=original, 1=first derived, etc.
    lineage_path     TEXT,    -- e.g. "root_id/derived1_id/derived2_id"

    -- Storage
    zarr_path        TEXT NOT NULL,
    channel_metadata TEXT,    -- JSON

    -- Status
    status           TEXT DEFAULT 'imported',
    -- 'imported' | 'segmented' | 'qc_pending' | 'qc_done' | 'analyzed' | 'stale' | 'error'
    status_updated_at TEXT,
    notes            TEXT,

    imported_at      TEXT DEFAULT (datetime('now'))
);
```

**`lineage_path`** enables fast tree queries without recursive CTEs:

```sql
-- All descendants of an original FOV
SELECT * FROM fovs WHERE lineage_path LIKE 'fov-abc123%';
```

---

### Cell Identity — Stable Anchor Across Derived Images

The problem: cell #47 from the original segmentation must be queryable across all derived FOVs.

```sql
CREATE TABLE cell_identities (
    id              TEXT PRIMARY KEY,  -- UUID, stable forever
    experiment_id   TEXT REFERENCES experiments(id),
    origin_fov_id   TEXT REFERENCES fovs(id),   -- always the original FOV
    origin_label_id INTEGER,    -- label number from original segmentation
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE rois (
    id                  TEXT PRIMARY KEY,
    cell_identity_id    TEXT REFERENCES cell_identities(id),  -- NULL for particles
    parent_roi_id       TEXT REFERENCES rois(id),             -- for particles: parent cell
    segmentation_run_id TEXT REFERENCES segmentation_runs(id),
    fov_id              TEXT REFERENCES fovs(id),
    roi_type            TEXT,   -- 'cell' | 'particle' | 'nucleus'
    label_id            INTEGER,
    bbox_x INTEGER, bbox_y INTEGER, bbox_w INTEGER, bbox_h INTEGER,
    polygon             TEXT,   -- JSON
    area_px             INTEGER
);
```

Query across the full derivation tree for one cell:

```sql
-- All measurements for cell identity ci-789, across every FOV in the lineage
SELECT
    f.auto_name        AS fov,
    f.derivation_op    AS derived_by,
    m.channel,
    m.metric,
    m.value
FROM measurements m
JOIN rois r  ON r.id = m.roi_id
JOIN fovs f  ON f.id = r.fov_id
WHERE r.cell_identity_id = 'ci-789'
ORDER BY f.lineage_depth, m.channel, m.metric;
```

---

### Intensity Groups

```sql
CREATE TABLE intensity_groups (
    id               TEXT PRIMARY KEY,
    threshold_run_id TEXT REFERENCES threshold_runs(id),
    group_index      INTEGER,       -- 0, 1, 2...
    group_label      TEXT,          -- 'low', 'mid', 'high' or user-defined
    lower_bound      REAL,
    upper_bound      REAL,
    cell_count       INTEGER,
    color_hex        TEXT,
    is_excluded      INTEGER DEFAULT 0   -- soft exclude; respected by all export queries
);

CREATE TABLE cell_group_assignments (
    roi_id             TEXT REFERENCES rois(id),
    intensity_group_id TEXT REFERENCES intensity_groups(id),
    grouping_value     REAL,   -- actual intensity value that placed them here
    PRIMARY KEY (roi_id, intensity_group_id)
);
```

Export with group filtering:

```sql
SELECT r.cell_identity_id, m.channel, m.metric, m.value
FROM measurements m
JOIN rois r   ON r.id = m.roi_id
JOIN cell_group_assignments cga ON cga.roi_id = r.id
JOIN intensity_groups ig ON ig.id = cga.intensity_group_id
WHERE m.measurement_run_id = 'mr-xyz'
  AND ig.is_excluded = 0
  -- optionally: AND ig.group_index IN (1, 2)
```

---

### Analysis Status Machine

Track status transitions explicitly alongside the current status column:

```sql
CREATE TABLE fov_status_log (
    id              TEXT PRIMARY KEY,
    fov_id          TEXT REFERENCES fovs(id),
    status          TEXT,
    pipeline_run_id TEXT,
    message         TEXT,
    logged_at       TEXT DEFAULT (datetime('now'))
);
```

Dashboard view:

```sql
CREATE VIEW analysis_dashboard AS
SELECT
    c.name                    AS condition,
    br.name                   AS bio_rep,
    f.display_name            AS fov,
    f.lineage_depth           AS depth,
    f.status,
    f.status_updated_at,
    CASE WHEN f.lineage_depth = 0
         THEN (SELECT COUNT(*) FROM rois r2
               JOIN cell_identities ci ON ci.id = r2.cell_identity_id
               WHERE ci.origin_fov_id = f.id)
         ELSE NULL
    END                       AS cell_count
FROM fovs f
JOIN bio_reps br  ON br.id = f.bio_rep_id
JOIN conditions c ON c.id = f.condition_id
ORDER BY c.name, br.name, f.lineage_depth, f.fov_index;
```

---

## Automatic FOV Naming

Naming is config-driven. Each derivation operation registers a short suffix:

```toml
[derivation_naming]
mask_subtract       = "msksubt"
background_subtract = "bgsub"
resegment           = "rseg"
separator           = "_"

# Result:
# ctrl_N1_001
#   └─ ctrl_N1_001_msksubt
#       └─ ctrl_N1_001_msksubt_rseg
#           └─ ctrl_N1_001_msksubt_rseg_bgsub
```

`LayerStore` constructs `auto_name` at derivation time:

```python
def derive_fov(self, parent: FOV, operation: str) -> FOV:
    suffix    = self.config.derivation_naming[operation]
    sep       = self.config.derivation_naming.separator
    auto_name = f"{parent.auto_name}{sep}{suffix}"
    zarr_path = f"zarr/images/{new_id}/"
    # auto_name also used as zarr group key for human browsability
```

---

## Workflow Configuration (TOML)

Config does two distinct things — kept separate:
- **`[op_configs.*]`** — how each operation runs (parameters)
- **`[[pipelines]]`** — what operations run and in what order (topology)

```toml
[experiment]
name = "P-body Two-Channel Sensor"

[[channels]]
name  = "sensor_ch1"
role  = "signal"
color = "green"

[[channels]]
name  = "sensor_ch2"
role  = "signal"
color = "red"

# ─── Named Operation Configs ───────────────────────────────────────────

[op_configs.cellpose_initial]
method   = "cellpose"
channel  = "sensor_ch1"
model    = "cyto3"
diameter = 30.0

[op_configs.threshold_round1]
channel            = "sensor_ch1"
grouping_channel   = "sensor_ch2"
method             = "otsu"
preprocessing      = { gaussian_blur_sigma = 1.5 }
post_dilation_px   = 3

[op_configs.mask_subtraction]
source_channel = "sensor_ch1"
mask_config    = "threshold_round1"

[op_configs.cellpose_round2]
method   = "cellpose"
channel  = "sensor_ch1"
model    = "cyto3"
diameter = 5.0
min_size = 3

[op_configs.background_estimation]
source_segmentation = "cellpose_round2"
method              = "mean_outside_mask"

[op_configs.background_subtraction]
per_cell = true
source   = "background_estimation"

[op_configs.final_measurement]
channels = ["sensor_ch1", "sensor_ch2"]
scope    = "inside_mask"
mask_config = "threshold_round1"   # use FIRST threshold mask for final measurement
metrics  = ["mean_intensity", "integrated_intensity", "area"]

# ─── Pipeline Topology ─────────────────────────────────────────────────

[[pipelines]]
name  = "pbody_full"
steps = [
  { step = "segment",    config = "cellpose_initial",      output_tag = "cells"       },
  { step = "threshold",  config = "threshold_round1",      output_tag = "mask1"       },
  { step = "derive_fov", config = "mask_subtraction",      output_tag = "fov_msksubt" },
  { step = "segment",    config = "cellpose_round2",       on = "fov_msksubt",  output_tag = "particles" },
  { step = "derive_fov", config = "background_subtraction",on = "fov_msksubt",  output_tag = "fov_bgsub" },
  { step = "measure",    config = "final_measurement",     on = "fov_bgsub"           },
]
```

`output_tag` values let subsequent steps reference prior outputs by logical name. The pipeline runner resolves tags to actual database IDs at execution time.

---

## UI Platform: Napari Plugin + TOML Config + CLI

**Napari plugin** for all interactive work. **TOML** for configuration. **CLI** for batch/headless runs. They share the same config and database — no duplication.

---

### Widget 1: Experiment Navigator

Replaces sifting through flat tables. Collapsible tree view keyed off `lineage_path`:

```
📁 P-body Screen
  📁 control
    📁 N1
      🔬 ctrl_N1_001            [✓ analyzed]
        └─ ctrl_N1_001_msksubt      [✓]
            └─ ctrl_N1_001_msksubt_rseg      [✓]
                └─ ctrl_N1_001_msksubt_rseg_bgsub  [✓ measured]
      🔬 ctrl_N1_002            [⚠ qc_pending]
      🔬 ctrl_N1_003            [○ imported]
  📁 treatment_10uM
    📁 N1
      🔬 treat_N1_001           [✓ analyzed]
      🔬 treat_N1_002           [✗ error]
```

- Single-click any node → loads image layer in napari canvas
- Double-click → loads with segmentation overlay
- Color-coded by status
- Filter by status ("show only: needs analysis")

---

### Widget 2: Cell Inspector

Click a cell in the napari canvas → shows:
- Cell identity ID and origin label number
- All measurements across all derived FOVs (mini table)
- Intensity group assignment
- Child particles with their measurements
- Exclude/include toggle for this specific cell

---

### Widget 3: Condition & Run Selector

Before running a pipeline:
- Multi-select checkboxes for conditions
- Multi-select for bio reps
- Status filter to find FOVs that need analysis
- Pipeline dropdown (reads from TOML `[[pipelines]]`)
- "Run selected" button with estimated FOV count preview

---

### Widget 4: Group Manager

After thresholding:
- Visual histogram of grouping distribution
- Each group shown as a colored band on the histogram
- Toggle groups on/off (sets `is_excluded` in DB)
- Rename groups (e.g. "low expresser", "high expresser")
- Live preview: "N cells in analysis after current exclusions"

---

### Widget 5: Export Builder

Not a single CSV dump — a query builder:
- Which conditions (multi-select)
- Which derived FOV level (original / msksubt / bgsub / all)
- Which channels
- Which metrics
- Include/exclude groups (respects `is_excluded` by default, overridable)
- Output format: CSV / Parquet / clipboard
- Row count estimate shown before export

---

## Full System Architecture

```
experiment.toml              ← version-controlled, defines everything
       │
       ▼
ExperimentConfig             ← Pydantic model, validates on load
(loaded at startup)
       │
   ┌───┴──────────────────────────────────┐
   │                                      │
   ▼                                      ▼
napari plugin                         CLI (batch / headless)
  - Experiment Navigator           percell4 run --config experiment.toml
  - Cell Inspector                 percell4 status --condition ctrl
  - Condition Selector             percell4 export --pipeline pbody_full
  - Group Manager
  - Export Builder
       │                                  │
       └──────────────┬───────────────────┘
                      ▼
             PipelineRunner
             - reads config topology
             - resolves output_tags to DB IDs
             - writes pipeline_runs records
             - creates derived FOVs with auto-names
             - updates FOV status machine
                      │
             ┌────────┴────────┐
             ▼                 ▼
         SQLite DB          Zarr Store
       - provenance        - images/      {fov_uuid}/
       - measurements      - segmentations/{seg_set_uuid}/{fov_uuid}/
       - cell_identities   - masks/       {mask_uuid}/
       - intensity_groups  - derived/     {dataset_uuid}/
       - fov status log
```

---

## Zarr Storage Layout

UUID-keyed so segmentation sets and masks are reusable across FOVs:

```
experiment.percell4/
├── experiment.toml
├── experiment.db
├── zarr/
│   ├── images/
│   │   └── {fov_id}/               ← original and derived FOVs
│   ├── segmentations/
│   │   └── {seg_set_id}/
│   │       └── {fov_id}/           ← per-FOV label arrays within the set
│   ├── masks/
│   │   └── {mask_id}/              ← reusable threshold masks
│   └── derived/
│       └── {dataset_id}/
└── exports/
```

---

## Decision Summary

| Requirement | Solution |
|---|---|
| Navigate derived FOVs without table-sifting | Napari tree widget driven by `lineage_path` column |
| Auto-naming of derived FOVs | Config-driven suffix table, constructed at derivation time by `LayerStore` |
| Cell identity across derived images | `CELL_IDENTITIES` table with stable UUID per physical cell |
| Particles linked to parent cells across FOVs | `parent_roi_id` on `ROIS`, resolved through `cell_identity_id` |
| Group include/exclude | `is_excluded` on `INTENSITY_GROUPS`, respected by all export queries |
| Know what's analyzed vs. pending | Status state machine on FOV + `analysis_dashboard` view |
| Fast export with flexible filters | Export Builder widget constructs parameterized SQL, single query |
| All data stored for future retrieval | Long/narrow `MEASUREMENTS` table — no metric is ever discarded |
| Workflow config with per-step params | TOML `[op_configs.*]` section separate from pipeline topology |
| Batch automation | CLI reads same TOML, same `PipelineRunner`, headless execution |

---

## Highest Priority Items to Get Right First

1. **`CELL_IDENTITIES` table and `lineage_path` column** — these are load-bearing. Every query for measurements, groups, and exports depends on them being correct. Get these right before writing any analysis code.

2. **Napari Experiment Navigator** — the difference between "powerful but painful" and "powerful and fast." Build this early so you're using it to validate the lineage system as you develop.
