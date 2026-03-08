---
title: "Layer-Based Architecture Redesign"
date: 2026-03-02
status: decided
type: refactor
supersedes: 2026-02-28-run-scoped-architecture-brainstorm.md
---

# Layer-Based Architecture Redesign

## What We're Building

A fundamental redesign of how segmentation, thresholding, and measurements interact. The core mental model shifts from "runs scoped to FOVs" to "independent layers composed through configuration."

**Key insight**: Segmentation, thresholding, and channel images are independent **layers** that exist globally. A configuration composes them per-FOV. Measurement is never a user action — it's an automatic side effect of creating or modifying layers.

## Why This Approach

The Phase 1-4 run-scoped architecture refactor delivered solid infrastructure but over-engineered the configuration layer (~560 lines of config management code). The user found the measurement configuration manager "confusing, not intuitive, and doesn't make sense." See `docs/solutions/architecture-decisions/run-scoped-architecture-refactor-learnings.md` for the full post-mortem.

The layer-based model aligns with how microscopists actually think: they have images, they overlay segmentation masks, they overlay threshold masks, and they measure what's in the intersection. The configuration is just setting up which overlays go on which images.

## Key Decisions

### 1. Segmentation and Thresholding Are Global Entities

Segmentation labels and threshold masks are **not** owned by FOVs. They exist once in the DB and once in zarr. Any FOV with matching dimensions can reference them.

- **Segmentation**: A 2D int32 label array. Divides an FOV into cells. Has `seg_type`: `whole_field` (default placeholder) or `cellular` (from Cellpose/hand-drawing).
- **Thresholding**: A 2D uint8 binary mask. Defines particle regions. Requires an active segmentation (the thresholding algorithm needs per-cell intensities for GMM grouping + Otsu).

Both have a `source_fov_id` column for provenance (which FOV they were created on), but this is metadata, not ownership.

### 2. Zarr Layout: Flat by ID

Zarr paths are keyed to DB primary keys, decoupled from FOV hierarchy:

```
labels.zarr/seg_{id}/0          # segmentation label arrays
masks.zarr/thresh_{id}/0        # threshold binary masks
masks.zarr/thresh_{id}/particles/0  # particle label arrays
images.zarr/fov_{id}/0          # channel images (unchanged)
```

Provenance lives in SQLite columns (`source_fov_id`), not baked into paths. CRUD is trivial: create writes to a new path, update overwrites in place, delete removes one group. Renaming is a SQLite column update with zero zarr cost.

### 3. Whole-Field Segmentation on Import

When an image is imported, the system automatically creates a `whole_field` segmentation — a label array where every pixel has label value 1. This is assigned as the FOV's active segmentation immediately.

**Consequences:**
- No FOV ever lacks a segmentation. Thresholding is always available from the moment of import.
- The `seg_type` column (`whole_field` vs `cellular`) distinguishes the default placeholder from real segmentations. A whole-field seg and a single-cell Cellpose result both have one label — only `seg_type` tells them apart.
- Whole-field segmentation serves double duty: default for new imports AND a deliberate analytical choice for field-level analysis.

### 4. Single Configuration Per Experiment (Matrix View)

One configuration per experiment, displayed as a matrix/table:
- **Rows**: FOVs
- **Columns**: Active segmentation, threshold(s), scope(s)
- All channels are always measured. All metrics are always computed.

**Auto-config behavior**: When a new segmentation or threshold is created, the config auto-updates to use it as the default for the FOVs it applies to. The user can override any assignment through the config manager.

**Per-FOV defaults**: Each FOV tracks its own layer assignments independently. Creating a segmentation on FOV1 and FOV2 doesn't affect FOV3's config.

**Persistence**: Configuration persists across program restarts (stored in SQLite).

**Scope selection**: User picks scopes per config row: `whole_cell`, `mask_inside`, `mask_outside`. This is the one per-FOV choice the user makes.

### 5. Measurement Is Fully Automatic

Measurement is a **side effect** of layer operations, never a user-initiated step:

| Action | Automatic Measurement |
|--------|----------------------|
| Create/edit segmentation | Measure all channels, whole_cell scope, using that segmentation |
| Create threshold | Extract particles (connected components), assign to cells via active seg, measure all channels for mask_inside/mask_outside |
| Edit labels in napari | Detect changed cells, delete old measurements, measure new/modified cells |
| Delete segmentation | Cascade delete all measurements that used it |
| Delete threshold | Cascade delete particle data + mask measurements |

**There is no "Re-measure" button.** Measurements are always in sync because they're produced at the moment the underlying layer is created/modified, and destroyed when that layer is destroyed.

The config is primarily a **view filter** — it determines which measurements to include in exports/analysis. However, it also detects unmeasured (seg, thresh) combinations and fills them in. When the user switches from segmentation A to segmentation B in the config, and measurements for (seg_B, thresh_X) don't yet exist, the system auto-computes them. So the config is a view filter that also triggers computation for missing combinations.

### 6. Particles Are FOV-Level Entities

Particles (connected components from threshold masks) are extracted once at threshold creation time and stored as FOV-level entities:

- **Static data**: `thresh_id`, `fov_id`, geometry (centroid, bbox), morphometrics (area, perimeter, circularity, eccentricity, solidity, axis lengths), per-particle intensity from source channel.
- **Dynamic data**: Cell-particle assignment (which particle belongs to which cell) is computed using the active segmentation's labels. Stored as part of measurement results, tagged with `seg_id + thresh_id`.

On initial threshold creation, both particle extraction and cell assignment happen together as part of auto-measurement — they are effectively the same moment. The distinction only matters when the user later switches segmentation in the config: the particles themselves don't change (they're a property of the threshold mask), but the cell assignment is recomputed for the new segmentation as part of the auto-computation of missing (seg, thresh) combinations.

### 7. Auto-Naming (Silent, Rename Later)

Naming never interrupts the workflow:

| Entity | Auto-name pattern | Example |
|--------|------------------|---------|
| Segmentation | `{model}_{channel}_{n}` | `cyto3_DAPI_001` |
| Hand-drawn seg | `hand_drawn_{channel}_{n}` | `hand_drawn_DAPI_002` |
| Threshold | `thresh_{grouping_ch}_{threshold_ch}_{n}` | `thresh_GFP_RFP_001` |
| Whole-field | `whole_field` | `whole_field` |

Numeric suffix handles multiple runs with the same model/channel. Rename through the config manager when in management mode (SQLite-only, zero zarr cost).

### 8. Measurement Provenance

Each measurement row stores provenance directly as columns:

```
measurements:
  seg_id        -- which segmentation produced this measurement
  thresh_id     -- which threshold (nullable for whole_cell scope)
  scope         -- whole_cell | mask_inside | mask_outside
  measured_at   -- timestamp
  config_id     -- FK to config active when measured (for audit/batch ops)
```

This makes the hot-path queries (export, comparison, plotting) fast — no joins needed to know which segmentation/threshold produced a measurement.

### 9. Dimension Validation

A segmentation can only be applied to FOVs with matching dimensions. The system validates this and rejects mismatches.

### 10. Thresholding Requires Active Segmentation

The thresholding workflow (measure per-cell intensity → GMM grouping → Otsu within groups) requires cell boundaries as input. The system enforces: thresholding is unavailable unless there's an active segmentation in the config. Since whole-field segmentation is auto-created on import, this is always satisfied — but the user needs to understand that thresholding against `whole_field` treats the entire FOV as one region.

### 11. Export Includes Config Provenance

When exporting measurements (CSV), the configuration is always printed with the export. The user knows exactly what was measured: which segmentation, which threshold(s), which scopes, which channels, for each FOV. If the user changes the config and re-exports, the new export reflects the new config.

## What Changes from Current Architecture

### Remove (~560 lines)
- `measurement_configs` table (replaced by simpler single-config model)
- `measurement_config_entries` table (replaced by per-FOV config rows)
- 7 CLI config management sub-handlers
- `auto_create_default_config()`
- Config CRUD queries

### Restructure
- `segmentation_runs` → `segmentations` (no longer "runs", no longer per-FOV scoped)
  - Remove `fov_id` FK (segmentations are global)
  - Add `source_fov_id` (provenance, not ownership)
  - Add `seg_type` column (`whole_field` | `cellular`)
  - Add `width`, `height` columns (for dimension validation)
- `threshold_runs` → `thresholds` (no longer "runs", no longer per-FOV scoped)
  - Remove `fov_id` FK, remove `channel_id` FK (thresholds are global)
  - Add `source_fov_id`, `source_channel_id` (provenance, not ownership)
  - Add `width`, `height` columns
- `cells` table
  - `segmentation_id` FK remains (cells belong to a segmentation)
- `particles` table
  - Change from `cell_id` FK to `fov_id` + `thresh_id` (FOV-level entities)
  - Cell-particle assignment moves to measurement pipeline
- `measurements` table
  - Add `seg_id` column (direct provenance)
  - Keep `thresh_id` column (nullable)
  - Add `measured_at` timestamp
  - Add `config_id` FK (audit grouping)
- Zarr paths: `fov_{id}/seg_{run_id}/0` → `seg_{id}/0` (flat by ID)
- Zarr paths: `fov_{id}/{channel}/run_{id}/mask/0` → `thresh_{id}/0` (flat by ID)

### Keep
- Named entities with UNIQUE constraints
- Scope-based measurements (whole_cell, mask_inside, mask_outside)
- Cascade delete with impact preview
- Plugin input requirements framework (InputKind enum)
- Run-scoped zarr paths concept (just different path pattern)

### New
- `fov_config` table (per-FOV layer assignments: seg_id, thresh_ids, scopes)
- `whole_field` segmentation auto-creation on import
- `seg_type` column on segmentations
- Auto-measurement pipeline (triggered by layer operations)
- Dimension validation on segmentation assignment
- Config provenance in exports

## Resolved Questions

1. **Are segmentation layers global or per-FOV?** Global. One entry in DB, one zarr group. Applied to multiple FOVs via config.
2. **Is thresholding attached to segmentation?** No. Both are independent layers. Thresholding *requires* an active segmentation for its algorithm, but the resulting mask is independent.
3. **Is thresholding attached to a channel?** No strict attachment. Created using a channel (recorded in metadata), but can be applied to any channel at measurement time.
4. **Where do zarr files live?** Flat by ID: `labels.zarr/seg_{id}/0`, `masks.zarr/thresh_{id}/0`.
5. **How are entities named?** Auto-named silently at creation. Rename through config manager (SQLite-only).
6. **When do measurements happen?** Automatically as a side effect of layer creation/modification. Never a user action.
7. **What about FOVs without segmentation?** Never happens — whole-field segmentation auto-created on import.
8. **How to distinguish whole-field from single-cell?** `seg_type` column: `whole_field` vs `cellular`.
9. **How are particles stored?** FOV-level entities (thresh_id + fov_id). Cell assignment computed at measurement time.
10. **Multiple configs or single?** Single per experiment. Config provenance printed with every export.
11. **What about re-measurement?** No re-measurement concept. Measurements are always in sync — produced when layers are created, destroyed when layers are deleted.
12. **What about measurement history?** Old measurements retained in DB, tagged with provenance (seg_id, thresh_id, config_id). Deleted only through explicit layer deletion or manual cleanup.

## Resolved Open Questions

13. **Config change + existing threshold measurements**: Keep both, compute on demand. When the user switches from seg A to seg B in the config, old (seg_A, thresh_X) measurements remain in the DB. New (seg_B, thresh_X) measurements are auto-computed when the config change is saved. Config determines which measurements to include in exports.

14. **Multiple thresholds in the config matrix**: One row per FOV-threshold combination. FOV1 with 2 thresholds = 2 rows. Each row shows: FOV | Segmentation | Threshold | Scopes. Flat and explicit, easy to scan.

15. **Migration path from current schema**: Fresh start only. New architecture applies only to new experiments. Old experiments continue using old code paths. No migration needed, avoids maintaining migration utilities, and keeps the implementation clean.

16. **Label editing: new entity vs overwrite**: Overwrite in place. When the user edits labels in napari and saves, the existing segmentation entity's zarr data is overwritten, changed cells are detected via `on_labels_edited()`, and measurements are incrementally updated. Creating a new entity per save would cause entity sprawl during iterative editing sessions. If the seg is shared across multiple FOVs, edits propagate to all — this is correct since sharing only applies to genuinely related FOVs (e.g., derived). The `on_labels_edited()` handler triggers measurement updates for **all FOVs in the config** that reference the edited segmentation, not just the one being viewed.

17. **Auto-measurement failure contract**: Layer persists, warn loudly. If auto-measurement fails (missing channel, 0 records), the segmentation/threshold entity is kept — it's a valid artifact regardless of measurement success. Log specifics: which channel missing, which FOV, which scope produced 0 records. Measurements auto-compute on the next gap-detection trigger (config change or next layer operation). Export includes a provenance note for FOVs with incomplete measurements but does not refuse to export.

18. **Deleting an active segmentation**: Allow with impact preview. Show what will be affected ("This segmentation is active on FOV_001, FOV_003. Deleting removes 342 cells, 1,847 measurements. Those FOVs revert to whole_field."). If user confirms, cascade delete + revert affected FOVs to whole_field. Consistent with the "delete explicitly, see what you're deleting" pattern already established.

19. **GMM with whole_field segmentation (N=1 cell)**: Skip GMM, apply global Otsu directly on the FOV's intensity histogram. With 1 region there is nothing to group — GMM requires multiple data points. This is a special-case branch in the thresholding pipeline when the active seg has only 1 cell.

20. **Plugin-created derived FOVs**: Yes, auto-measure derived FOVs. `add_fov()` creates a whole_field segmentation and fires auto-measurement for all FOVs, including plugin-created derived FOVs. Plugin CSV exports coexist with the standard measurement system. No special-case handling.

21. **Multiple label layers in napari viewer**: Not an issue in the new architecture. The viewer loads exactly one label layer — the active segmentation from the FOV's config. No ambiguity about which layer to save. The old bug (multiple label layers from multiple seg runs) is eliminated by design since config determines what's loaded.
