---
title: "feat: Import FOVs from another PerCell project"
type: feat
date: 2026-03-04
---

# feat: Import FOVs from Another PerCell Project

## Overview

Add a feature to import selected FOVs from one percell3 project into another, carrying over all associated data: channel images, segmentation labels, threshold masks, cells, measurements, particles, cell tags, and fov_config. This preserves prior analysis work without re-segmenting, re-thresholding, or re-measuring.

## Problem Statement / Motivation

Users often need to combine FOVs from different experiments for comparative analysis. Currently there is no way to merge data across percell3 projects — the only option is to re-import raw images and re-run the entire analysis pipeline. This wastes time and makes cross-experiment comparison impractical.

## Proposed Solution

A new `PerCellImporter` module in `src/percell3/io/percell_import.py` that:

1. Opens a source `.percell` project read-only
2. Presents FOVs for selection
3. Builds an ID remapping table (source IDs → destination IDs)
4. Copies all data with remapped IDs, per-FOV atomicity

CLI integration via new "Import from PerCell project" menu item under IMPORT.

## Technical Approach

### Architecture

```
CLI (menu.py)
  └── PerCellImporter (io/percell_import.py)
        ├── Opens source ExperimentStore (read-only)
        ├── Builds RemapTable
        ├── Copies SQLite entities (channels, conditions, segs, thresholds, cells, measurements, particles, tags)
        ├── Copies zarr data (images, labels, masks, particle_labels)
        └── Uses destination ExperimentStore API for all writes
```

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Channel matching | By name (reuse existing) | Avoids duplicates when projects share channels |
| Condition/bio_rep matching | By name (reuse existing) | Same rationale |
| Segmentation dedup | One new seg per unique source seg_id | Preserves shared-seg architecture |
| Whole-field seg | Reuse destination's auto-created | Auto-created by `add_fov()` |
| Threshold import | Always new ID, unique name | Thresholds are analysis-specific |
| FOV name collision | Auto-rename with `_imported_{n}` suffix | Non-blocking UX |
| Seg/threshold name collision | Auto-rename with `_imported_{n}` suffix | Match existing `_generate_*_name()` pattern |
| Channel re-indexing | Per-channel read/write | Source/dest may have different display_order |
| Transaction boundary | Per-FOV atomic (cleanup on failure) | Partial imports recoverable |
| Cell tags | Included | Critical for group analysis |
| Same-project guard | Reject with error | Prevents self-referential duplication |
| Analysis runs | Not imported | Different experiment context |
| Timepoints | Matched by name | Consistent with conditions/bio_reps |

### ID Remapping Strategy

```python
# src/percell3/io/percell_import.py

@dataclass
class RemapTable:
    """Maps source project IDs to destination project IDs."""
    fov: dict[int, int] = field(default_factory=dict)
    segmentation: dict[int, int] = field(default_factory=dict)
    threshold: dict[int, int] = field(default_factory=dict)
    cell: dict[int, int] = field(default_factory=dict)
    channel: dict[int, int] = field(default_factory=dict)
    condition: dict[int, int] = field(default_factory=dict)
    bio_rep: dict[int, int] = field(default_factory=dict)
    tag: dict[int, int] = field(default_factory=dict)
    timepoint: dict[int, int] = field(default_factory=dict)
```

### Channel Re-indexing (Critical)

Source and destination may have different `display_order` for channels. The zarr image array is `(C, Y, X)` where C is indexed by `display_order`. The import **must not** copy zarr directories — it must read each channel individually from the source and write to the correct destination channel index.

```python
# For each FOV, for each channel:
src_image = src_store.read_image_numpy(src_fov_id, channel_name)
dst_store.write_image(dst_fov_id, channel_name, src_image)
# write_image() handles display_order mapping internally
```

### Per-FOV Atomic Import

Each FOV import is wrapped in try/except. On failure, cleanup via `delete_fov()` (CASCADE deletes cells, measurements, particles, config) + zarr cleanup.

```python
for src_fov_id in selected_fov_ids:
    dst_fov_id = None
    try:
        dst_fov_id = _import_single_fov(src_store, dst_store, src_fov_id, remap)
    except Exception as exc:
        if dst_fov_id is not None:
            try:
                dst_store.delete_fov(dst_fov_id)
            except Exception:
                pass
        warnings.append(f"Failed to import FOV {src_fov_id}: {exc}")
        continue
```

### Implementation Phases

#### Phase 1: Core Import Engine

- [x] Create `src/percell3/io/percell_import.py` with `PerCellImporter` class
- [x] Implement `RemapTable` dataclass
- [x] Implement entity matching/creation:
  - [x] `_match_channels()` — match by name, create missing
  - [x] `_match_conditions()` — match by name, create missing
  - [x] `_match_bio_reps()` — match by name, create missing
  - [x] `_match_timepoints()` — match by name, create missing
- [x] Implement `_import_single_fov()`:
  - [x] Create FOV in destination (auto-creates whole_field seg)
  - [x] Map auto-created whole_field seg to source whole_field seg
  - [x] Copy channel images (per-channel, re-indexed)
  - [x] Handle FOV display_name collision (auto-rename)
- [x] Implement segmentation import:
  - [x] Deduplicate: one new seg per unique source seg_id
  - [x] Create segmentation with unique name (`_imported_{n}` suffix on collision)
  - [x] Copy label images from `labels.zarr`
  - [x] Set `source_fov_id` to remapped ID or NULL
- [x] Implement threshold import:
  - [x] Create threshold with unique name
  - [x] Copy mask from `masks.zarr`
  - [x] Copy particle labels from `masks.zarr`
  - [x] Set `source_fov_id` to remapped ID or NULL
- [x] Implement cell import:
  - [x] Read source cells, remap `fov_id` and `segmentation_id`
  - [x] Batch insert with `add_cells()`, capture new IDs in remap table
- [x] Implement measurement import:
  - [x] Read source measurements, remap `cell_id`, `channel_id`, `segmentation_id`, `threshold_id`
  - [x] Batch insert (respect 900-row batching for status cache update)
- [x] Implement particle import:
  - [x] Read source particles, remap `fov_id`, `threshold_id`
  - [x] Batch insert with `add_particles()`
- [x] Implement tag import:
  - [x] Match/create tags by name in destination
  - [x] Copy cell_tags with remapped `cell_id` and `tag_id`
- [x] Implement fov_config import:
  - [x] Read source fov_config, remap `segmentation_id`, `threshold_id`
  - [x] Create entries via `set_fov_config_entry()`
- [x] Call `update_fov_status_cache()` for each imported FOV
- [x] Add same-project guard (compare resolved paths)

#### Phase 2: CLI Integration

- [x] Add "Import from PerCell project" to `_import_menu()` in `src/percell3/cli/menu.py`
- [x] Implement source path prompt (text input with validation)
- [x] Implement FOV selection UI:
  - [x] Display numbered list grouped by condition
  - [x] Support multi-select (space-separated numbers)
  - [x] Support "all" shortcut
- [x] Implement import summary display:
  - [x] Count of FOVs, channels, segmentations, thresholds
  - [x] Warnings for name collisions, new channels to create
- [x] Implement confirmation prompt
- [x] Implement progress feedback (per-FOV with Rich progress bar)
- [x] Implement result summary display

#### Phase 3: Tests

- [x] Create `tests/test_io/test_percell_import.py`
- [x] Test basic import: 1 FOV, 1 channel, no seg/threshold
- [x] Test channel matching: reuse existing channel by name
- [x] Test channel creation: new channel created when missing
- [x] Test channel re-indexing: different display_order in source vs dest
- [x] Test condition/bio_rep matching
- [x] Test segmentation import: cellular seg with cells
- [x] Test whole_field seg reuse: auto-created seg is mapped correctly
- [x] Test threshold import: mask + particle labels + particles
- [x] Test measurement import: remapped cell_id, channel_id, seg_id, threshold_id
- [x] Test cell tag import: tags created and remapped
- [x] Test FOV name collision: auto-rename with suffix
- [x] Test seg/threshold name collision: auto-rename
- [x] Test per-FOV atomicity: failure on one FOV doesn't corrupt others
- [x] Test same-project guard: rejected with error
- [x] Test empty FOV: FOV with images but no cells
- [x] Test multi-FOV shared seg: one seg created, shared by imported FOVs

## Acceptance Criteria

### Functional Requirements

- [x] User can import FOVs from another `.percell` project via IMPORT menu
- [x] All channel images are copied with correct channel indexing
- [x] All segmentation labels are copied and cells remapped
- [x] All threshold masks and particle labels are copied and particles remapped
- [x] All measurements are copied with fully remapped IDs
- [x] Cell tags (including group tags) are preserved
- [x] Channels, conditions, bio_reps matched by name; created if missing
- [x] FOV display_name collisions auto-resolved with suffix
- [x] Segmentation/threshold name collisions auto-resolved with suffix
- [x] Import is atomic per-FOV (failure cleans up partial data)
- [x] Self-import (same project) is rejected

### Non-Functional Requirements

- [x] No source project modification (read-only access)
- [x] Batch inserts respect SQLite 999 bind parameter limit
- [x] Progress feedback shown during import

## Technical Considerations

### Source Project Access Pattern

Open source as a second `ExperimentStore` in read-only mode. The source's SQLite database is opened normally (reads don't modify). Zarr data is read via `read_image_numpy()`, `read_labels()`, `read_mask()`, `read_particle_labels()`.

```python
src_store = ExperimentStore.open(source_path)  # read-only usage
try:
    importer = PerCellImporter(src_store, dst_store)
    result = importer.import_fovs(selected_fov_ids)
finally:
    src_store.close()
```

### Query Methods Needed from Source

Reading source data requires these ExperimentStore methods (all existing):

| Data | Method |
|------|--------|
| FOV list | `get_fovs()` |
| FOV info | `get_fov_by_id(fov_id)` |
| Channels | `get_channels()` |
| Conditions | `get_conditions()` |
| Bio reps | `get_bio_reps()` |
| FOV config | `get_fov_config(fov_id)` |
| Segmentations | `get_segmentation(seg_id)` |
| Thresholds | `get_threshold(thr_id)` |
| Cells | `get_cells(fov_id=fov_id)` |
| Measurements | `get_measurements_for_fov(fov_id)` or raw query |
| Particles | raw query by `fov_id` |
| Cell tags | raw query by `cell_id` |
| Tags | `get_tags()` or raw query |
| Channel images | `read_image_numpy(fov_id, channel)` |
| Labels | `read_labels(seg_id)` |
| Masks | `read_mask(thr_id)` |
| Particle labels | `read_particle_labels(thr_id)` |

Some queries (measurements by fov_id, particles by fov_id, cell_tags by cell_id) may need new query functions or direct SQL on the source connection. Check existing query coverage and add minimal helpers if needed.

### Learnings to Apply

From `docs/solutions/`:
1. **Dual-store consistency** — zarr writes and SQLite inserts must be synchronized; use per-FOV atomicity with cleanup on failure
2. **Batch safety** — batch inserts to ≤900 rows for SQLite bind param limit
3. **ID mapping** — use explicit mapping tables, never list indexing
4. **Name validation** — all names validated via `_validate_name()` at entry
5. **Control flow separation** — don't catch `_MenuCancel` with validation errors

## Dependencies & Risks

| Risk | Mitigation |
|------|------------|
| Channel re-indexing bug silently swaps data | Per-channel read/write via store API (not zarr directory copy) |
| OOM on large FOVs | Read/write per-channel, not entire CYX array at once |
| Partial import on crash | Per-FOV atomic with `delete_fov()` cleanup |
| SQLite bind param overflow | Batch inserts ≤900 rows |
| Source corruption | Never open source zarr in write mode |

## References & Research

### Internal References

- Brainstorm: `docs/brainstorms/2026-03-04-import-fovs-from-percell-project-brainstorm.md`
- ExperimentStore: `src/percell3/core/experiment_store.py`
- Schema: `src/percell3/core/schema.py`
- Zarr I/O: `src/percell3/core/zarr_io.py`
- Existing import flow: `src/percell3/cli/menu.py` (`_import_menu()`)
- Queries: `src/percell3/core/queries.py`
- Models: `src/percell3/core/models.py`

### Learnings Applied

- `docs/solutions/database-issues/zarr-sqlite-state-mismatch-re-thresholding.md` — dual-store consistency
- `docs/solutions/security-issues/core-module-p1-security-correctness-fixes.md` — input validation, atomic inserts
- `docs/solutions/design-gaps/import-flow-table-first-ui-and-heuristics.md` — import UI patterns
- `docs/solutions/architecture-decisions/layer-based-architecture-redesign-learnings.md` — global entities, whole-field seg
- `docs/solutions/architecture-decisions/tile-scan-stitching-import-implementation-and-code-review.md` — ID mapping patterns
