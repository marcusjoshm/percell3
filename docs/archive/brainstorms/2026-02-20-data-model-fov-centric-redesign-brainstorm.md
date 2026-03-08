---
title: "PerCell 3 Data Model Redesign — FOV-Centric Flat Architecture"
type: feat
date: 2026-02-20
---

# PerCell 3 Data Model Redesign: FOV-Centric Flat Architecture

## What We're Building

A fundamental restructuring of how PerCell 3 organizes experiment data. The core change: **every FOV becomes an independent, globally-identifiable unit of data** with condition, bio_rep, and tech_rep as filterable labels rather than mandatory structural parents.

This fixes recurring errors caused by the rigid `condition → bio_rep → FOV` hierarchy (e.g., "Multiple bio reps exist (1, 2); specify one explicitly") and enables flexible, status-aware batch operations on any subset of FOVs.

## Problem Statement

### The hierarchy creates friction everywhere

The current schema enforces: `conditions → bio_reps (NOT NULL FK) → fovs (NOT NULL FK) → cells → measurements/particles`.

Every image read/write must decompose a FOV into `(name, condition, bio_rep)` via `_resolve_fov()`. But FOV names are NOT globally unique — two conditions can each have "FOV_001". This causes:

1. **Ambiguity errors**: "Multiple bio reps exist; specify one explicitly" — the code can't resolve which FOV you mean without the full hierarchy path
2. **Unnecessary drill-down**: napari viewer forces condition → bio_rep → FOV navigation while every other operation uses flat FOV tables
3. **Brittle API**: Every `read_image()`, `write_labels()`, `write_mask()` call requires condition parameter even when you already have the FOV object
4. **Zarr path coupling**: Images live at `{condition}/{bio_rep}/{fov}/` — renaming a condition requires physically moving zarr groups

### Analysis doesn't care about hierarchy

For segmentation, measurement, and thresholding, the condition/bio_rep labels are irrelevant. They only matter at export time for grouping results. The analysis pipeline already treats FOVs as independent units in the UI (flat table selection across conditions), but the schema and API fight against this.

### Status tracking is implicit and expensive

"Has this FOV been segmented?" requires JOINing `fovs → cells → segmentation_runs`. "Has it been measured?" requires joining through measurements. The `select_experiment_summary()` query does 4-way LEFT JOINs with subqueries. This will get slow as experiments grow to hundreds of FOVs.

## Why This Approach

### Industry patterns support FOV-centric models

- **QuPath**: Each image is an independent `ProjectImageEntry` with a unique ID, editable name, key-value metadata, and tags. Status is tracked via `summary.json` cache + `hasImageData()` inference.
- **CellProfiler**: Flat image sets with metadata columns extracted from filenames. Processing status inferred from output existence.
- **OMERO**: Images are independent entities with flexible `MapAnnotation` key-value pairs and `TagAnnotation` labels. Many-to-many relationships, not rigid hierarchy.

All three treat images as the atomic unit with labels/tags for organization — none enforce a structural hierarchy for metadata.

### PerCell 3 is halfway there already

The analysis UI (segment, measure, threshold) already presents FOVs as a flat table with cross-condition selection. Export queries globally. The experiment summary is per-FOV. The hierarchy only constrains: (1) the schema/API layer, (2) zarr storage paths, (3) napari viewer navigation.

## Key Decisions

### 1. FOV is the atomic, multi-dimensional unit

A FOV contains:
- Multiple channels (DAPI, GFP, etc.)
- Optionally multiple timepoints, z-slices, and/or tiles
- Extensible for future data types (FLIM/TCSPC histograms)
- All dimensions grouped under one FOV with a unique identifier

This aligns with the OME-NGFF model already in use (zarr arrays are naturally multi-dimensional).

### 2. Dual identity: unique ID + editable display name

- **`fov.id`** (integer, auto-increment): The true identity. All internal code, API methods, and zarr paths use this. Never displayed to users, never typed by users.
- **`fov.display_name`** (text, unique): Auto-generated composite name (e.g., `HS_VCPi_N1_FOV_001`) that users see in tables and can edit. Generated from condition + bio_rep + sequential number at import time.

All `ExperimentStore` methods switch from `(fov_name, condition, bio_rep)` signatures to `fov_id` parameter.

### 3. Labels required but flat (no hierarchy chain)

**New schema concept:**
```
fovs:
  id              INTEGER PRIMARY KEY
  display_name    TEXT UNIQUE NOT NULL
  condition_id    INTEGER NOT NULL REFERENCES conditions(id)
  bio_rep_id      INTEGER NOT NULL REFERENCES bio_reps(id)
  width, height, pixel_size_um, ...
```

Key changes from current schema:
- `bio_reps` no longer has `condition_id` FK — bio_reps become a flat list of replicate labels (e.g., "N1", "N2") that aren't scoped to conditions
- FOV has **direct** references to both condition and bio_rep (not chained through bio_rep → condition)
- Condition and bio_rep are still required (needed for export/reporting) but the chain is broken
- Tech_rep becomes a new optional label column on FOV (or a fov_metadata key-value pair)

This eliminates the decomposition problem: given a `fov_id`, you can directly read its condition, bio_rep, and images without resolving through a chain.

### 4. Zarr storage: flat by FOV ID

Images stored at `images.zarr/fov_{id}/` instead of `images.zarr/{condition}/{bio_rep}/{fov}/`.

Benefits:
- Renaming a condition or bio_rep is just a DB update — no zarr group moves
- No path ambiguity
- FOV identity is stable regardless of label changes

Trade-off: browsing the zarr file externally (napari standalone, zarr viewer) shows `fov_1/`, `fov_2/` instead of human-readable paths. The SQLite DB is the directory for human-readable names.

### 5. Status cache table

Maintain a `fov_status_cache` table updated after each operation:

```
fov_status_cache:
  fov_id          INTEGER PRIMARY KEY REFERENCES fovs(id)
  cell_count      INTEGER DEFAULT 0
  seg_model       TEXT
  measured_channels   TEXT (comma-separated)
  masked_channels     TEXT (comma-separated)
  particle_channels   TEXT (comma-separated)
  particle_count  INTEGER DEFAULT 0
  updated_at      TEXT
```

- Updated at the end of each segmentation, measurement, and threshold operation
- JOIN-based inference (`select_experiment_summary()`) remains as the source of truth for reconciliation
- The cache serves the UI: FOV status table, filtering, batch selection all read from cache
- Periodic reconciliation (or on-demand via a "refresh status" action) ensures cache accuracy

### 6. Column filters + user-defined tags

**Filtering:** When displaying the FOV status table, users can filter by:
- Condition (e.g., `condition=HS`)
- Bio rep (e.g., `bio_rep=N1`)
- Analysis status (e.g., `status=not-measured`, `status=segmented`)
- Tags (e.g., `tag=reprocess`, `tag!=QC-failed`)

**Tags:** Short string labels attached to FOVs via a `fov_tags` junction table (similar to existing `cell_tags`). Users can:
- Create tags ad-hoc (e.g., `QC-failed`, `reprocess`, `batch-2`, `imported-late`)
- Add/remove tags from FOVs via the Edit menu
- Filter by tags in any FOV selection table
- Tags are searchable and composable with other filters

### 7. API redesign: FOV-ID-first

All `ExperimentStore` public methods that currently take `(fov, condition, bio_rep)` switch to `fov_id`:

**Current:** `store.read_image(channel, fov, condition, bio_rep=None, timepoint=None)`
**New:** `store.read_image(fov_id, channel, timepoint=None)`

**Current:** `store.write_labels(labels, fov, condition, bio_rep=None, run_id=None)`
**New:** `store.write_labels(fov_id, labels, run_id=None)`

This eliminates `_resolve_fov()` and the entire decomposition step that causes ambiguity errors.

## Scope and Phasing

This is a large refactor touching the schema, ExperimentStore API, zarr I/O, all CLI handlers, and tests. Suggested phases:

1. **Schema migration**: Flatten the FOV table, add display_name, add fov_status_cache, add fov_tags
2. **ExperimentStore API**: Switch all methods to fov_id-based signatures, update zarr path generation
3. **CLI handlers**: Update all menu handlers to use FovInfo.id instead of (name, condition, bio_rep)
4. **Filtering**: Add filter prompts to FOV selection tables
5. **Migration tool**: Convert existing experiments from hierarchical to flat storage

## Resolved Questions

1. **TUI vs CLI?** — Stay with Rich CLI (decided in menu UI redesign brainstorm)
2. **Unit of data?** — FOV is the atomic multi-dimensional unit (channels, timepoints, z-slices, tiles, extensible for FLIM)
3. **FOV identity?** — Auto-generated unique ID for internal use + auto-generated composite display name (editable) for users
4. **Hierarchy depth?** — Labels required but flat. No condition→bio_rep→FOV chain. Direct references from FOV to both.
5. **Status tracking?** — Status cache table + JOIN inference as source of truth
6. **Filtering?** — Column filters + user-defined tags (via fov_tags junction table)
7. **Zarr layout?** — Flat by FOV ID (`images.zarr/fov_{id}/`)
8. **API style?** — All methods take `fov_id` instead of `(name, condition, bio_rep)` decomposition

## Resolved Questions (continued)

9. **Migration** — This is early-stage development, not production data. Breaking changes are acceptable. No migration tool needed — bump schema version, old experiments won't open.
10. **Bio_rep scoping** — Experiment-global. One "N1" entity shared across all conditions. This reflects biological reality: replicate N1 is the same biological sample measured under different conditions. The `bio_reps` table becomes a flat list of replicate labels with no condition FK. This supports incremental import across days and filling in ruined samples.
11. **Display name collisions** — Auto-append number suffix. If `HS_N1_FOV_001` already exists, the second becomes `HS_N1_FOV_001_2`. Automatic, no user interruption.
