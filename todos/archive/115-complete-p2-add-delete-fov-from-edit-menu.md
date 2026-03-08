---
status: complete
priority: p2
issue_id: "115"
tags: [code-review, cli, core, feature]
dependencies: []
---

# Add delete FOV/image function to edit experiment menu

## Problem Statement

The edit experiment menu (`Data > Edit experiment`) only supports rename operations. There is no way to delete FOVs (images) from the CLI. This is needed to remove derived FOVs (`condensed_phase_*`, `dilute_phase_*`) or unwanted images without manually editing the database and zarr stores.

## Findings

- **Found by:** user request + repo exploration
- **Location:** `src/percell3/cli/menu.py:2308-2378` (edit menu), `src/percell3/core/experiment_store.py`
- Current edit menu has 5 rename-only items
- `ExperimentStore` has `delete_cells_for_fov()` and `delete_particles_for_fov()` but no `delete_fov()` method
- Deleting a FOV requires: removing from `fovs` table, cascading to cells/measurements/particles, and removing zarr groups from `images.zarr`, `labels.zarr`, `masks.zarr`
- `fov_status_cache` and `fov_tags` tables have `ON DELETE CASCADE` so they auto-clean

## Proposed Solutions

### Solution A: Add delete_fov() to ExperimentStore + CLI menu item (Recommended)

1. Add `ExperimentStore.delete_fov(fov_id: int)` that:
   - Calls `delete_particles_for_fov(fov_id)`
   - Calls `delete_cells_for_fov(fov_id)`
   - Deletes threshold runs referencing the FOV
   - Removes zarr groups: `images.zarr/fov_{id}`, `labels.zarr/fov_{id}`, `masks.zarr/fov_{id}`
   - Deletes the `fovs` row
2. Add `_delete_fov()` handler to CLI with multi-select and confirmation
3. Add as MenuItem #6 in `_edit_menu()`

- **Pros:** Clean public API, reusable, follows hexagonal architecture
- **Cons:** Need to handle zarr deletion carefully (shutil.rmtree on zarr groups)
- **Effort:** Medium
- **Risk:** Low — all cascades are well-defined

## Technical Details

**Affected files:**
- `src/percell3/core/experiment_store.py` — add `delete_fov()` method
- `src/percell3/core/queries.py` — add `delete_fov_row()` query
- `src/percell3/core/zarr_io.py` — add `delete_fov_data()` for zarr cleanup
- `src/percell3/cli/menu.py` — add menu item and handler
- `tests/test_core/test_experiment_store.py` — add deletion tests

## Acceptance Criteria

- [ ] `store.delete_fov(fov_id)` removes all database rows and zarr data
- [ ] CLI menu shows delete option with FOV list and confirmation prompt
- [ ] Cascading deletes cover cells, measurements, particles, masks, labels, images
- [ ] Tests verify complete cleanup
