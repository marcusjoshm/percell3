---
topic: run-scoped-architecture
status: decided
date: 2026-02-28
supersedes: docs/brainstorms/2026-02-27-named-threshold-runs-and-state-consistency-brainstorm.md
---

# Run-Scoped Architecture: Named Segmentation & Threshold Runs with Full Provenance

## What We're Building

A fundamental restructuring of PerCell 3's data model to support **named, independently managed segmentation and threshold runs** with full measurement provenance. This replaces the current single-overwrite model where re-segmenting or re-thresholding destroys previous results.

### Core Capabilities

1. **Multiple named segmentation runs per FOV** — e.g., `cellpose_d30` and `cellpose_d50` on the same image, both preserved
2. **Multiple named threshold runs per FOV+channel** — e.g., `otsu_strict` and `otsu_liberal` on the same GFP channel, each with its own particle set
3. **Full measurement provenance** — every measurement records which segmentation run AND which threshold run produced it
4. **Run management** — add, delete, rename, combine (union/intersect), copy across FOVs
5. **Measurement configuration module** — persistent, named configurations mapping FOVs to seg/threshold run combinations, set up before measurement, reusable
6. **Cross-run measurement flexibility** — any segmentation run can be paired with any threshold run for measurement
7. **Run-aware napari viewer** — when viewing a FOV, napari loads layers based on current measurement configuration; multiple segmentation and threshold layers visible simultaneously
8. **Organized multi-file exports** — CSV files organized by segmentation layer and threshold/particle layer
9. **Auto-generated names with rename** — system suggests names from method+params, user can rename anytime

### Non-Goals

- **Schema migration** from existing `.percell` experiments. Existing experiments must be re-imported. Tag stable version for continued use.
- **Undo/redo** for run operations. Deletes are permanent (with confirmation).
- **Plugin interface changes.** Plugins continue using ExperimentStore API; they gain new methods but existing methods remain.
- **`analysis_runs` table integration.** The current `analysis_runs` table (plugin execution records) remains unchanged. Linking plugin outputs to analysis runs is a separate future concern — this refactor focuses on segmentation and threshold run provenance.
- **Cell tag run-awareness.** Tags (`cell_tags`, `fov_tags`) remain cell-scoped, not run-scoped. Cells from different segmentation runs have different IDs and thus independent tags.

## Why This Approach

### Problem

The current schema has fundamental single-overwrite constraints:
- ONE label image per FOV (re-segmentation overwrites)
- ONE mask per FOV+channel (re-thresholding overwrites)
- `measurements` UNIQUE constraint `(cell_id, channel_id, metric, scope)` allows only ONE measurement value — second run overwrites first
- `segmentation_runs` and `threshold_runs` lack `fov_id` and `name` columns
- No Zarr run-level namespacing — all stored at `fov_{id}/0`

This blocks new analysis workflows: background subtraction with derived images, multiple thresholding rounds, applying masks/segmentation to derived images, and measuring multiple particle layers.

### Chosen Approach: Run-Scoped (Approach A)

Named runs are the primary organizational unit. No extra abstraction layers.

**Rejected alternative:** Analysis Context model (bundles seg run + threshold runs into a named group). This can be layered on later if needed, but adds unnecessary complexity now.

## Key Decisions

### Data Model

#### 1. Schema Changes

**`segmentation_runs` table:**
- ADD `fov_id INTEGER NOT NULL` (FK to fovs, CASCADE on delete)
- ADD `name TEXT NOT NULL` (auto-generated, renameable)
- ADD `UNIQUE(fov_id, name)` — one name per FOV
- KEEP `channel_id`, `model_name`, `parameters`, `cell_count`, `created_at`
- **Batch operations:** Segmenting 10 FOVs creates 10 independent rows (one per FOV), each with the same auto-generated name. No batch grouping — each FOV's run is managed independently.

**`threshold_runs` table:**
- ADD `fov_id INTEGER NOT NULL` (FK to fovs, CASCADE on delete)
- ADD `name TEXT NOT NULL` (auto-generated, renameable)
- ADD `UNIQUE(fov_id, channel_id, name)` — one name per FOV+channel
- KEEP `channel_id`, `method`, `parameters`, `threshold_value`, `created_at`

**`measurements` table:**
- CHANGE UNIQUE constraint to `(cell_id, channel_id, metric, scope, threshold_run_id)` — allows same metric measured with different thresholds
- `threshold_run_id` remains nullable for whole_cell scope measurements (no threshold involved)
- **Note:** `segmentation_run_id` is NOT added to measurements. It is redundant because every `cell_id` already belongs to exactly one segmentation run via `cells.segmentation_id`. Provenance is recovered by joining: `measurements.cell_id → cells.segmentation_id → segmentation_runs`.
- KEEP all other columns

**`cells` table:**
- No changes needed — already references `segmentation_id`

**`particles` table:**
- No changes needed — already references `threshold_run_id` and has `UNIQUE(cell_id, threshold_run_id, label_value)`

**`analysis_runs` table:**
- No changes — remains as-is. Linking plugin outputs to analysis runs is out of scope (see Non-Goals).

**ON DELETE CASCADE additions:**
- `cells.fov_id` → CASCADE (delete FOV = delete its cells)
- `cells.segmentation_id` → CASCADE (delete seg run = delete its cells → cascades to measurements and particles)
- `particles.cell_id` → CASCADE (delete cell = delete its particles)
- `particles.threshold_run_id` → CASCADE (delete threshold run = delete its particles)
- `measurements.cell_id` → CASCADE
- `measurements.threshold_run_id` → CASCADE (delete threshold run = delete its mask-scoped measurements)

**Why CASCADE (not SET NULL) for `measurements.threshold_run_id`:** Mask-scoped measurements (mask_inside, mask_outside) are meaningless without their threshold run reference — the measurement values were computed against that specific mask. SET NULL would create orphaned measurements that lost their provenance and could collide with whole_cell measurements (where threshold_run_id is NULL) on the UNIQUE constraint. CASCADE is the correct semantic: if you delete the threshold run, its dependent measurements go with it. Whole_cell measurements (which have `threshold_run_id = NULL`) are unaffected because they belong to the cell, not the threshold run.

**NULL handling in UNIQUE constraints:** SQLite treats each NULL as distinct in UNIQUE constraints. This means:
- For `measurements`: two rows with `threshold_run_id = NULL` and the same `(cell_id, channel_id, metric, scope)` would both be allowed. This is acceptable because whole_cell measurements should only be inserted once per cell — enforced at the application level by the measurement engine.
- For `measurement_config_entries`: use `COALESCE(threshold_run_id, 0)` in a unique index to prevent duplicate whole_cell-only entries (see Section 7).

#### 2. Zarr Layout Changes

**Labels (segmentation):**
- Current: `labels.zarr/fov_{id}/0`
- New: `labels.zarr/fov_{id}/seg_{run_id}/0`

**Masks (thresholds):**
- Current: `masks.zarr/fov_{id}/threshold_{channel}/0`
- New: `masks.zarr/fov_{id}/{channel}/run_{run_id}/mask/0`

**Particles:**
- Current: `masks.zarr/fov_{id}/particles_{channel}/0`
- New: `masks.zarr/fov_{id}/{channel}/run_{run_id}/particles/0`

Run IDs (not names) in Zarr paths for storage stability — renames only touch SQLite.

**Zarr cleanup on run deletion:** CASCADE handles SQLite cleanup, but Zarr groups on the filesystem are NOT automatically deleted. The `delete_segmentation_run()` and `delete_threshold_run()` ExperimentStore methods must explicitly delete the corresponding Zarr groups after the SQLite CASCADE completes. This is similar to the existing pattern where `write_mask()` overwrites Zarr data.

#### 3. fov_status_cache Redesign

**Deferred to planning phase.** Current cache stores comma-separated strings. The new multi-run model requires either:
- **Option A:** JSON blob per FOV (simple, flexible)
- **Option B:** Normalized table with one row per FOV+run (queryable)

Both work; tradeoff is query simplicity vs schema rigidity. Will be decided during implementation planning.

### API & Operations

#### 4. Name Auto-Generation

Format: `{method}_{key_params}` — e.g.:
- Segmentation: `cellpose_d30_flow0.4`
- Threshold: `otsu_t128` or `manual_t200`
- Copy operations: `copy_from_fov3`
- Combine operations: `union_strict_liberal`

**Name collision handling:** If auto-generated name collides with an existing name for the same FOV (or FOV+channel), append a numeric suffix: `cellpose_d30_flow0.4_2`, `cellpose_d30_flow0.4_3`, etc.

Names editable via `rename_segmentation_run()` / `rename_threshold_run()`.

#### 5. Run Management Operations

| Operation | Segmentation | Threshold |
|-----------|-------------|-----------|
| Create (new analysis) | `add_segmentation_run()` | `add_threshold_run()` |
| List | `list_segmentation_runs(fov_id)` | `list_threshold_runs(fov_id, channel)` |
| Rename | `rename_segmentation_run(run_id, new_name)` | `rename_threshold_run(run_id, new_name)` |
| Delete | `delete_segmentation_run(run_id)` → CASCADE SQLite + delete Zarr | `delete_threshold_run(run_id)` → CASCADE SQLite + delete Zarr |
| Copy to FOV | `copy_segmentation_to_fov(run_id, target_fov_id)` — copies labels, re-analyzes to compute cell properties | `copy_threshold_to_fov(run_id, target_fov_id)` |
| Combine | N/A (segmentation labels can't be unioned) | `combine_threshold_runs(run_ids, op='union'|'intersect', name)` |

#### 6. Mask Combine Operations

- **Union (OR):** New mask = any pixel set in any source mask. Creates new threshold run with `method='union'`, parameters recording source run IDs.
- **Intersect (AND):** New mask = pixels set in ALL source masks. Creates new threshold run with `method='intersect'`.
- **Cross-FOV transfer:** Creates new run with `method='copy'`, parameters recording source FOV + run ID.

All combine operations create new named runs with full provenance — never mutate existing runs.

**Combine operations create masks only — no immediate particle analysis.** The combined mask is stored as a new threshold run, but particle extraction is deferred to measurement time. When the user measures using a measurement config that references the combined threshold run, the measurement engine runs particle analysis against whichever segmentation run is paired with it in the config. This avoids the ambiguity of which segmentation run's cells should "own" the particles.

### User-Facing

#### 7. Measurement Configuration Module

Instead of selecting runs at measurement time (error-prone), users pre-configure a **measurement configuration** that maps the full matrix of FOVs, segmentation runs, and threshold runs before executing.

**New tables:**

```sql
measurement_configs (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
)

measurement_config_entries (
  id INTEGER PRIMARY KEY,
  config_id INTEGER NOT NULL REFERENCES measurement_configs(id) ON DELETE CASCADE,
  fov_id INTEGER NOT NULL REFERENCES fovs(id),
  segmentation_run_id INTEGER NOT NULL REFERENCES segmentation_runs(id) ON DELETE CASCADE,
  threshold_run_id INTEGER REFERENCES threshold_runs(id) ON DELETE CASCADE
  -- nullable: NULL means whole_cell only; non-NULL adds mask-scoped + particle measurements
)

-- Use COALESCE to handle NULL in unique index (SQLite treats NULLs as distinct)
CREATE UNIQUE INDEX idx_config_entry_unique
  ON measurement_config_entries(config_id, fov_id, segmentation_run_id, COALESCE(threshold_run_id, 0));
```

**Scope semantics:** A single config entry triggers ALL applicable measurement scopes automatically:
- Entry with `threshold_run_id = NULL` → whole_cell measurements only
- Entry with `threshold_run_id = X` → whole_cell + mask_inside + mask_outside + particle measurements

The measurement engine determines which scopes apply based on available data — users don't configure scopes individually.

**Run deletion:** If a segmentation or threshold run referenced by a config entry is deleted, the config entry is CASCADE-deleted too. The configuration may become incomplete — this is acceptable since the underlying data no longer exists.

**Active configuration:** The most recently created configuration is active by default. User changes the active config through the "Setup" menu in the CLI.

**Workflow:**
1. User creates/edits a named measurement configuration via CLI "Setup" menu
2. Configuration presents a table of all FOVs with their available seg runs and threshold runs
3. User selects which combinations to measure (any seg run + any threshold run, full cross-referencing)
4. Configuration is saved persistently — can be re-run anytime
5. "Measure" operation reads the active configuration and executes all selected measurements

**Cross-referencing example:** Measure particles from `otsu_strict` threshold run using cell boundaries from `cellpose_d50` segmentation — even though the original thresholding was done with `cellpose_d30` cells. The measurement config maps: FOV 1 → `cellpose_d50` seg run → `otsu_strict` threshold run.

**UI:** CLI interactive menu (Rich-based table). Napari widgets handle single-FOV operations; batch measurement configuration is a CLI workflow.

#### 8. Run-Aware Napari Viewer

When a user selects an FOV to view in napari, the viewer loads layers based on the **active measurement configuration**. Multiple segmentation and threshold layers can be displayed simultaneously on a single FOV.

**Layer loading behavior:**

When opening a FOV, napari loads:
1. **Image channels** — all raw channel images (DAPI, GFP, etc.) as always
2. **Segmentation layers** — one napari Labels layer per segmentation run configured for this FOV, named by run name (e.g., `cellpose_d30 [labels]`, `cellpose_d50 [labels]`)
3. **Threshold mask layers** — one napari Image layer per threshold run configured for this FOV+channel, named by run name (e.g., `otsu_strict [GFP mask]`, `otsu_liberal [GFP mask]`)
4. **Particle label layers** — one napari Labels layer per threshold run that has particles, named accordingly (e.g., `otsu_strict [GFP particles]`)

**Configuration-driven display:**

- The active measurement configuration (most recent by default, changeable via CLI "Setup" menu) determines which runs appear as layers
- If no configuration exists, show ALL available runs for the FOV (discovery mode)
- User can toggle layer visibility in napari's layer list to compare runs side by side
- Each layer is clearly labeled with the run name to avoid confusion

**Multi-layer example for a single FOV:**

```
napari layers (top to bottom):
  otsu_liberal [GFP particles]    ← Labels layer, particles from liberal threshold
  otsu_strict [GFP particles]     ← Labels layer, particles from strict threshold
  otsu_liberal [GFP mask]         ← Image layer, liberal threshold mask
  otsu_strict [GFP mask]          ← Image layer, strict threshold mask
  cellpose_d50 [labels]           ← Labels layer, loose segmentation
  cellpose_d30 [labels]           ← Labels layer, strict segmentation
  GFP                             ← Image layer, raw channel
  DAPI                            ← Image layer, raw channel
```

**Run selection widget:** A dock widget showing available runs for the current FOV with checkboxes to control which layers are loaded. This is separate from the measurement configuration — it's for interactive exploration. The measurement configuration drives batch measurement; the viewer widget drives visual exploration.

#### 9. Plugin Run Selection

Plugins that operate on a single segmentation or threshold layer must handle the case where multiple runs exist for the target FOV.

**Behavior when multiple runs are available:**

1. Plugin declares its input requirements (e.g., "needs one segmentation run" or "needs one threshold run for channel X")
2. If the current measurement configuration specifies exactly one matching run for the FOV, use it automatically
3. If multiple matching runs exist (either in the config or in the FOV), prompt the user to select which one via a dropdown/combo box in the plugin's parameter UI
4. The selected run is recorded in the plugin's `parameters` JSON for provenance

**Example — Split Halo Condensate Analysis plugin:**
- Requires: one segmentation run (for cell boundaries) + one threshold run per channel (for particle detection)
- If FOV has `cellpose_d30` and `cellpose_d50`: plugin UI shows a "Segmentation Run" combo box with both options
- If FOV has `otsu_strict` and `otsu_liberal` on GFP: plugin UI shows a "GFP Threshold Run" combo box
- Selected runs recorded in `analysis_runs.parameters`: `{"segmentation_run_id": 3, "threshold_run_ids": {"GFP": 7}}`

**Plugin API pattern:**
- `store.list_segmentation_runs(fov_id)` → populate combo box
- `store.list_threshold_runs(fov_id, channel)` → populate combo box
- Plugin receives selected run IDs as parameters, reads the corresponding Zarr data

This ensures plugins work correctly without assuming a single active run, while keeping the selection explicit and traceable.

#### 10. Export Structure

```
exports/
  {experiment_name}/
    {segmentation_name}/
      whole_cell_measurements.csv      # cells + whole_cell scope metrics
      {threshold_name}/
        mask_measurements.csv          # mask_inside/mask_outside scope metrics
        particles.csv                  # per-particle measurements
    summary/
      segmentation_runs.csv            # run metadata (name, method, params, cell_count)
      threshold_runs.csv               # run metadata per channel
```

Each CSV includes provenance columns: `fov_name`, `segmentation_run`, `threshold_run` (where applicable).

## What This Absorbs from Pending Work

### Todos Eliminated by This Refactor (10 items)

| ID | Problem | How It's Solved |
|----|---------|----------------|
| 120 | Stale mask measurements on re-threshold | Run-scoped measurements — no overwrites, clean deletes via CASCADE |
| 123 | threshold_runs missing fov_id | Core schema change |
| 124 | Orphaned segmentation_runs | CASCADE deletes + explicit run management |
| 125 | Missing composite index | Designed into new schema |
| 126 | Missing ON DELETE CASCADE | Added to all relevant FKs |
| 127 | Re-segmentation stale masks | Named runs — no overwrites, old runs preserved or explicitly deleted |
| 129 | Cache not updated after cleanup | Cache redesigned |
| 130 | N+1 cache update | Batch update in new design |
| 132 | Duplicated schema DDL | Fixed during schema rewrite |
| 133 | Hardcoded particle metrics | Addressed in new constants module |

### Todos Addressed During Refactor (3 items)

| ID | Problem | How It's Addressed |
|----|---------|-------------------|
| 119 | Transaction safety in particle cleanup | New write patterns must use proper transactions; not automatically solved by schema change alone — must be implemented correctly |
| 121 | Bind param overflow (>999 cells) | Query batching pattern applied during refactor implementation |
| 122 | Layering violation (queries imports measure) | Fix architectural boundary during refactor |

### Todos Not Addressed (remain independent)

| ID | Problem | Why Independent |
|----|---------|----------------|
| 128 | analysis_runs disconnected from outputs | Out of scope — see Non-Goals |
| 131 | Plugin CSVs accumulate without cleanup | Partially addressed by new export structure (deterministic filenames per run), but plugin CSV behavior is independent of schema |

### Pending Feature Absorbed

- **Named Threshold Runs** brainstorm → fully superseded by this broader design

## Reprioritized Work Queue

### Tier 0: Preserve Stable Version
- Tag current `main` as `v0.1.0-stable`
- Create feature branch for architecture work

### Tier 1: Schema & Core (Build First)
1. New schema with named runs (segmentation + threshold)
2. Zarr layout with run-level namespacing
3. ExperimentStore API: CRUD for named runs
4. Run-scoped measurements with provenance
5. Fix #121 (bind param batching) and #122 (layering violation) during refactor
6. CASCADE deletes for clean run removal + Zarr cleanup
7. Measurement configuration module (tables + CLI)

### Tier 2: Operations, Viewer & Export (Build Next)
1. Run-aware napari viewer (multi-layer display, run selection widget)
2. Mask combine operations (union, intersect)
3. Cross-FOV copy with provenance tracking
4. Multi-file organized CSV exports
5. Auto-generated run names with rename support
6. Updated segmentation/threshold widgets for run selection

### Tier 3: Independent Quality Work (Parallel or After)
- 109: Filter edge cells mutation and performance
- 110: Edge margin missing post-init validation
- 113: SQL bind param limit (group tags query)
- 134: Copy Labels/Mask widget code duplication (~90% identical)
- 135: SplitHaloCondensateAnalysis.run() is 200+ lines — extract _process_cell()
- 136: Core copy functions live inside widget files (need pure-Python module)
- 137: _create_derived_fovs uses Any type + mixed CSV column types
- 104: Remove redundant back menu items
- 105: Inconsistent blank-equals-all behavior
- 107: Auto-measure before grouping if no measurements
- 108: Napari edge cell removal widget
- 111: Deduplicate gaussian smoothing pattern
- 112: Deduplicate group tag merge pattern
- 115: Add delete FOV from edit menu
- 116: Threshold viewer not showing gaussian blur
- 117: Configurable min particle size threshold
- 118: Colormaps not visible in main napari viewer

### Tier 4: Independent Features (After Core)
- TIFF Export (plan ready, small effort)
- Per-Condition Channel Support (plan ready, large effort)
- Replace tkinter with Qt dialogs (small effort)

### Deferred
- Cell Tracking Multi-Timepoint (depends on stable multi-run system)
- Analysis Context layer (Approach B — add if needed later)

## Resolved Questions

1. **Multiple segmentations per FOV?** → Yes, full support with named runs
2. **Measurement provenance in exports?** → Full provenance columns, organized multi-file exports by seg/threshold layer
3. **Run naming?** → Auto-generated from method+params, user can rename anytime. Collisions resolved with numeric suffix.
4. **Combine operations?** → Union, intersect, and cross-FOV transfer — all creating new tracked runs
5. **Backward compatibility?** → Breaking schema is OK. Tag current stable version for continued use during development. No migration code — re-import required.
6. **Multiple particle layers?** → Same channel, multiple thresholds each producing independent particle sets
7. **Run selection at measurement time?** → No. Pre-configure via a persistent **measurement configuration module** (CLI interactive menu). User sets up the full FOV/seg/threshold matrix before measuring.
8. **Measurement configuration persistence?** → Persistent and reusable. Saved as named configurations in the DB, re-runnable anytime.
9. **Cross-run measurements?** → Full cross-referencing. Any segmentation run can be paired with any threshold run on the same FOV.
10. **Configuration UI?** → CLI interactive menu (Rich-based). Napari handles single-FOV interactive work; batch measurement config is a CLI workflow.
11. **CASCADE vs SET NULL on threshold_run_id?** → CASCADE. Mask-scoped measurements are meaningless without their threshold run. Deleting a threshold run removes its dependent measurements.
12. **segmentation_run_id on measurements?** → Not needed. Cell ID already implies segmentation run via cells.segmentation_id. Avoids redundancy.
13. **Zarr cleanup on run deletion?** → ExperimentStore delete methods explicitly remove Zarr groups after SQLite CASCADE.
14. **Napari viewer with multiple runs?** → Configuration-driven. Active measurement config determines which layers load. Multiple segmentation and threshold layers displayed simultaneously per FOV. Run selection widget for interactive exploration.
15. **Plugin run selection?** → Plugins that need a single run prompt the user via combo box when multiple runs exist. Selection recorded in plugin parameters for provenance. If measurement config specifies exactly one matching run, use it automatically.
16. **Batch segmentation creates one row per FOV?** → Yes. Segmenting 10 FOVs creates 10 independent rows with the same auto-generated name. No batch grouping needed.
17. **What scopes does a config entry trigger?** → All applicable. Entry with threshold_run_id triggers whole_cell + mask_inside + mask_outside + particle measurements. NULL threshold_run_id triggers whole_cell only.
18. **Config entries when runs are deleted?** → CASCADE delete. Config may become incomplete — acceptable since underlying data no longer exists.
19. **How does a config become active?** → Most recently created is active by default. User changes active config via CLI "Setup" menu.
20. **Segmentation copy — what about cells?** → Re-analyze the label image on the target FOV to compute cell properties (centroids, areas, bboxes). Don't copy cell records directly.
21. **Mask combine — which cells own the particles?** → Deferred. Combine creates mask only. Particle analysis runs at measurement time using whichever segmentation run is paired in the measurement config.

## Open Questions

None — all questions resolved during brainstorming.
