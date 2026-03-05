---
title: "feat: Unassign segmentations and thresholds from FOVs"
type: feat
date: 2026-03-04
---

# feat: Unassign Segmentations and Thresholds from FOVs

## Overview

Add the ability to unassign (unlink) a segmentation or threshold from specific FOVs without deleting the entity itself. The `fov_config` table already supports this — `delete_fov_config_entry()` exists. This feature adds CLI integration under "Manage segmentations" and "Manage thresholds" with proper data cleanup.

## Problem Statement / Motivation

Currently, segmentations and thresholds can only be **deleted entirely** (removing all associated cells, measurements, particles, and config entries across ALL FOVs) or left assigned. There is no way to unlink a segmentation or threshold from a specific FOV while keeping it assigned to others. This is needed when:

- A threshold was mistakenly assigned to the wrong FOV
- A segmentation is shared across many FOVs but should be removed from some
- The user wants to re-run analysis on specific FOVs without affecting others

## Proposed Solution

Add "Unassign from FOVs" as a new action in both `_manage_seg_runs()` and `_manage_thr_runs()` in `menu.py`. For thresholds, this also cleans up associated particle-level measurements and particles. For segmentations, it cleans up cells, all measurements (including particle measurements), particles, and config entries for the affected FOV.

## Technical Approach

### Architecture

```
CLI (menu.py)
  ├── _manage_seg_runs() → "Unassign from FOVs" action
  │     └── ExperimentStore.unassign_segmentation_from_fov(seg_id, fov_id)
  │           ├── Delete fov_config entries for (fov_id, seg_id)
  │           ├── Delete measurements for cells belonging to (fov_id, seg_id)
  │           ├── Delete particles for (fov_id) linked to thresholds in affected config
  │           ├── Delete cells for (fov_id, seg_id)
  │           └── Update FOV status cache
  └── _manage_thr_runs() → "Unassign from FOVs" action
        └── ExperimentStore.unassign_threshold_from_fov(thr_id, fov_id)
              ├── Delete fov_config entries where threshold_id = thr_id AND fov_id = fov_id
              ├── Delete measurements with threshold_id for cells in fov_id
              ├── Delete particles for (fov_id, thr_id)
              └── Update FOV status cache
```

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Cleanup scope (threshold) | Delete particle measurements + particles for that FOV+threshold | Measurements reference threshold_id; orphaned data is confusing |
| Cleanup scope (segmentation) | Delete cells + all their measurements + particles | Cells belong to the segmentation; cascade cleanup is necessary |
| Whole_field seg protection | Block unassignment | Whole_field seg is auto-created per FOV; unassigning breaks invariants |
| Last cellular seg warning | Warn but allow | User may want to reassign a different segmentation |
| FOV selection | Multi-select from FOVs that have the seg/threshold assigned | Only show relevant FOVs |
| Config entry deletion | Via existing `delete_fov_config_entry()` | Reuse existing API |
| Transaction safety | Single transaction wrapping all cleanup | Atomic operation prevents partial cleanup |
| Zarr data | Not deleted | Segmentation labels and threshold masks stay on disk; only config links and DB records are removed |

### Data Cleanup Strategy

#### Threshold Unassignment

When unassigning threshold `T` from FOV `F`:

1. Find `fov_config` entries where `fov_id = F AND threshold_id = T`
2. Delete measurements where `threshold_id = T AND cell_id IN (cells of FOV F)`
3. Delete particles where `fov_id = F AND threshold_id = T`
4. Delete the `fov_config` entries found in step 1
5. Update FOV status cache for `F`

**New query needed:** `delete_measurements_for_fov_threshold(conn, fov_id, threshold_id)` — deletes measurements that have `threshold_id = T` and belong to cells in FOV `F`.

#### Segmentation Unassignment

When unassigning segmentation `S` from FOV `F`:

1. Find `fov_config` entries where `fov_id = F AND segmentation_id = S`
2. For each config entry with a `threshold_id`, delete particles for `(F, threshold_id)`
3. Delete all measurements for cells belonging to `(F, S)` — `DELETE FROM measurements WHERE cell_id IN (SELECT id FROM cells WHERE fov_id = F AND segmentation_id = S)`
4. Delete cells for `(F, S)` — `DELETE FROM cells WHERE fov_id = F AND segmentation_id = S`
5. Delete the `fov_config` entries found in step 1
6. Update FOV status cache for `F`

### Implementation Phases

#### Phase 1: Query Layer

- [x] Add `delete_measurements_for_fov_threshold(conn, fov_id, threshold_id)` to `queries.py`
- [x] Add `delete_measurements_for_fov_segmentation(conn, fov_id, segmentation_id)` to `queries.py`
- [x] Add `delete_cells_for_fov_segmentation(conn, fov_id, segmentation_id)` to `queries.py`

#### Phase 2: ExperimentStore Methods

- [x] Add `unassign_threshold_from_fov(threshold_id, fov_id)` to `experiment_store.py`
  - [x] Find and delete fov_config entries
  - [x] Delete particle measurements
  - [x] Delete particles
  - [x] Update status cache
- [x] Add `unassign_segmentation_from_fov(segmentation_id, fov_id)` to `experiment_store.py`
  - [x] Guard: reject if seg_type == 'whole_field'
  - [x] Find and delete fov_config entries (including threshold cleanup)
  - [x] Delete measurements for cells
  - [x] Delete cells
  - [x] Update status cache
- [x] Add `get_fov_ids_for_segmentation(segmentation_id)` helper if not existing
- [x] Add `get_fov_ids_for_threshold(threshold_id)` helper if not existing

#### Phase 3: CLI Integration

- [x] Add "Unassign from FOVs" option to `_manage_seg_runs()` action list
  - [x] Select segmentation
  - [x] Guard: block whole_field segmentation
  - [x] Show FOVs that have this segmentation assigned (via fov_config)
  - [x] Multi-select FOVs to unassign from
  - [x] Show impact preview (cells, measurements, particles to be removed)
  - [x] Confirm before proceeding
  - [x] Call `unassign_segmentation_from_fov()` per FOV
  - [x] Display result
- [x] Add "Unassign from FOVs" option to `_manage_thr_runs()` action list
  - [x] Select threshold
  - [x] Show FOVs that have this threshold assigned (via fov_config)
  - [x] Multi-select FOVs to unassign from
  - [x] Show impact preview (measurements, particles to be removed)
  - [x] Confirm before proceeding
  - [x] Call `unassign_threshold_from_fov()` per FOV
  - [x] Display result
- [x] Update menu item descriptions: "List, rename, delete, or unassign segmentations/thresholds"

#### Phase 4: Tests

- [x] Test `delete_measurements_for_fov_threshold()` in `tests/test_core/`
- [x] Test `delete_measurements_for_fov_segmentation()` in `tests/test_core/`
- [x] Test `unassign_threshold_from_fov()` — verify measurements and particles removed, config entry deleted, other FOVs unaffected
- [x] Test `unassign_segmentation_from_fov()` — verify cells, measurements, particles removed, config entry deleted
- [x] Test whole_field segmentation guard — rejected with error
- [x] Test unassign from FOV that doesn't have the seg/threshold — no-op or clear message
- [x] Test multi-FOV unassignment — each FOV cleaned up independently
- [x] Test status cache updated after unassignment

## Acceptance Criteria

### Functional Requirements

- [x] User can unassign a segmentation from specific FOVs via "Manage segmentations" menu
- [x] User can unassign a threshold from specific FOVs via "Manage thresholds" menu
- [x] Whole_field segmentations cannot be unassigned (clear error message)
- [x] All associated measurements, particles, and cells are cleaned up
- [x] Other FOVs sharing the same segmentation/threshold are unaffected
- [x] Impact preview shown before confirmation
- [x] FOV status cache updated after unassignment

### Non-Functional Requirements

- [x] Cleanup is atomic (all-or-nothing per FOV)
- [x] Batch deletes respect SQLite 999 bind parameter limit
- [x] Zarr data is NOT deleted (only config links and DB records)

## Technical Considerations

### Existing Code to Leverage

| Existing | Use For |
|----------|---------|
| `delete_fov_config_entry(entry_id)` | Remove config link |
| `delete_particles_for_fov_threshold(fov_id, thr_id)` | Remove particles |
| `select_fov_config(config_id, fov_id)` | Find config entries |
| `get_segmentation(seg_id)` | Check seg_type for whole_field guard |
| `update_fov_status_cache(fov_id)` | Refresh cache after changes |
| `get_segmentation_impact(seg_id)` / `get_threshold_impact(thr_id)` | Pattern for impact preview |

### New Code Needed

| New | Purpose |
|-----|---------|
| `delete_measurements_for_fov_threshold()` | Delete measurements with threshold_id for cells in a FOV |
| `delete_measurements_for_fov_segmentation()` | Delete measurements for cells belonging to FOV+seg |
| `delete_cells_for_fov_segmentation()` | Delete cells for a specific FOV+segmentation |
| `unassign_threshold_from_fov()` | Orchestrate threshold unassignment with cleanup |
| `unassign_segmentation_from_fov()` | Orchestrate segmentation unassignment with cleanup |

### Learnings Applied

- `docs/solutions/logic-errors/combined-mask-overwrites-last-group-threshold.md` — verify particle data with SQL, not visual inspection; always clean up downstream data when removing upstream config
- `docs/solutions/database-issues/zarr-sqlite-state-mismatch-re-thresholding.md` — dual-store consistency; zarr and SQLite must stay in sync (here we choose to NOT delete zarr data, keeping it as orphaned but harmless)
- `docs/solutions/architecture-decisions/run-scoped-architecture-refactor-learnings.md` — fov_config is the assignment layer; mutations to it should cascade to affected measurements

## References

### Internal References

- ExperimentStore: `src/percell3/core/experiment_store.py`
  - `delete_fov_config_entry()` at line 1121
  - `set_fov_config_entry()` at line 1065
  - `delete_segmentation()` at line 898
  - `delete_threshold()` at line 1022
- Queries: `src/percell3/core/queries.py`
  - `delete_particles_for_fov_threshold()` at line 981
  - `select_fov_config()` at line 1067
  - `delete_fov_config_entry()` at line 1125
- CLI menus: `src/percell3/cli/menu.py`
  - `_manage_seg_runs()` at line 3188
  - `_manage_thr_runs()` at line 3240
- Schema: `src/percell3/core/schema.py`
  - fov_config table: `segmentation_id NOT NULL`, `threshold_id` nullable
  - `CHECK(seg_type IN ('whole_field', 'cellular'))`
