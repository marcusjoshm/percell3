---
title: "Unassign Segmentations and Thresholds from FOVs"
category: architecture-decisions
date: 2026-03-04
tags: [fov-config, cleanup-orchestration, unassignment, cascade-delete, data-integrity]
module: core, cli
symptom: "No way to remove a segmentation or threshold from specific FOVs without deleting the entity globally"
root_cause: "Only global deletion existed; fov_config supported per-FOV unlinking but no orchestration layer cleaned up associated data"
---

# Unassign Segmentations and Thresholds from FOVs

## Problem

Users could only **delete** segmentations and thresholds globally (removing all cells, measurements, particles, and config entries across every FOV) or leave them assigned. There was no way to unlink a segmentation or threshold from a specific FOV while keeping it assigned to others.

This gap mattered when:
- A threshold was mistakenly assigned to the wrong FOV
- A segmentation shared across many FOVs needed removal from some
- Re-running analysis on specific FOVs without affecting others

The low-level building block existed (`delete_fov_config_entry()`), but simply deleting the config link left orphaned measurements, particles, and cells in the database — stale data that would appear in exports.

## Investigation

### Existing Architecture

The `fov_config` table is the assignment layer linking FOVs to segmentations and thresholds:

```sql
CREATE TABLE fov_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config_id INTEGER NOT NULL REFERENCES analysis_config(id) ON DELETE CASCADE,
    fov_id INTEGER NOT NULL REFERENCES fovs(id) ON DELETE CASCADE,
    segmentation_id INTEGER NOT NULL REFERENCES segmentations(id) ON DELETE CASCADE,
    threshold_id INTEGER REFERENCES thresholds(id) ON DELETE SET NULL,
    scopes TEXT NOT NULL DEFAULT '["whole_cell"]'
);
```

Key schema properties:
- `segmentation_id` is NOT NULL with CASCADE — deleting the segmentation removes the config entry
- `threshold_id` is nullable with SET NULL — deleting the threshold nullifies rather than removing

### Why `delete_fov_config_entry()` Alone Was Insufficient

Calling `delete_fov_config_entry()` removes the config link but leaves:
- **Measurements** still referencing the threshold_id for cells in that FOV
- **Particles** still referencing the fov_id + threshold_id
- **Cells** still referencing the fov_id + segmentation_id
- **FOV status cache** not updated (stale display)

### Auto-Config Behavior Discovery

During testing, discovered that `_auto_config_segmentation()` creates **two** config entries per FOV when a cellular segmentation is added with a source_fov_id:
1. A base entry `(seg_id, threshold_id=None)` — replacing the whole_field entry
2. A threshold entry `(seg_id, threshold_id=T)` — added by `set_fov_config_entry()`

This means unassigning a segmentation typically deletes 2+ config entries, not 1.

## Solution

Three-layer implementation: query functions, store orchestration, CLI integration.

### Layer 1: Query Functions (`queries.py`)

Three new targeted delete functions:

```python
def delete_measurements_for_fov_threshold(conn, fov_id, threshold_id) -> int:
    """Delete measurements with a specific threshold_id for cells in a FOV."""
    # Uses subquery: WHERE threshold_id = ? AND cell_id IN (SELECT id FROM cells WHERE fov_id = ?)

def delete_measurements_for_fov_segmentation(conn, fov_id, segmentation_id) -> int:
    """Delete all measurements for cells belonging to a specific FOV + segmentation."""
    # Uses subquery: WHERE cell_id IN (SELECT id FROM cells WHERE fov_id = ? AND segmentation_id = ?)

def delete_cells_for_fov_segmentation(conn, fov_id, segmentation_id) -> int:
    """Delete cells for a specific FOV + segmentation."""
    # Also cleans up measurements and cell_tags before deleting cells
```

Each function counts affected rows first, returns 0 early if nothing to delete, and commits after deletion.

### Layer 2: Store Orchestration (`experiment_store.py`)

Two new methods with proper cleanup ordering (follows FK dependency chain):

**Threshold unassignment** — `unassign_threshold_from_fov(threshold_id, fov_id)`:
1. Find matching `fov_config` entries
2. Delete threshold-scoped measurements for cells in this FOV
3. Delete particles for this FOV + threshold (reuses existing `delete_particles_for_fov_threshold`)
4. Delete the config entries
5. Update FOV status cache

**Segmentation unassignment** — `unassign_segmentation_from_fov(segmentation_id, fov_id)`:
1. **Guard**: Reject `whole_field` segmentations (auto-managed per FOV)
2. Find matching `fov_config` entries
3. For each entry with a threshold_id, delete particles
4. Delete all measurements for cells in this FOV + segmentation
5. Delete cells for this FOV + segmentation
6. Delete the config entries
7. Update FOV status cache

Both methods return a dict with deletion counts and are idempotent (calling twice returns all zeros on the second call).

### Layer 3: CLI Integration (`menu.py`)

Added "Unassign from FOVs" as a fourth action in both `_manage_seg_runs()` and `_manage_thr_runs()`:
- Filters to cellular segmentations only (whole_field blocked)
- Shows only FOVs that have the entity assigned
- Multi-select FOVs to unassign from
- Confirmation prompt before proceeding
- Displays deletion totals per category

Updated menu item descriptions from "List, rename, or delete" to "List, rename, delete, or unassign".

### Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Cleanup scope | Delete downstream data (measurements, particles, cells) | Orphaned data causes confusion in exports |
| Zarr data | NOT deleted | Labels/masks on disk are harmless; only DB records and config links removed |
| Whole_field guard | Block unassignment | Auto-created per FOV; unassigning breaks invariants |
| Transaction safety | Atomic per FOV | Each FOV's cleanup is committed together |
| Idempotency | Second call is a no-op | Returns all-zero counts, no errors |

## Testing

15 tests in `tests/test_core/test_unassign.py`:

- **Threshold unassignment** (5 tests): correct deletion counts, other FOV data preserved, non-threshold measurements preserved, no-op when not assigned, config entry removed
- **Segmentation unassignment** (5 tests): cells + measurements removed, other FOV data preserved, whole_field guard, no-op when not assigned, config entry removed
- **Query-level functions** (5 tests): targeted deletion with isolation verification, no-op on empty data

All 1326 tests pass with no regressions.

## Key Lessons

1. **`delete_fov_config_entry()` does NOT cascade** — unlike entity deletion which triggers SQLite CASCADE constraints, removing a config link leaves all computed data intact. Any "unassign" operation must explicitly clean up downstream data.

2. **Auto-config creates multiple entries** — `_auto_config_segmentation()` replaces whole_field entries, creating both base and threshold entries. Test assertions must account for 2+ config entries per assignment, not 1.

3. **Deletion order matters** — Follow FK dependency chain: particles -> measurements -> cells -> config entries. Reversing the order would violate constraints or leave orphaned data.

4. **Zarr data can be safely orphaned** — Label images and threshold masks on disk have no FK references. Leaving them avoids filesystem operations and allows potential re-assignment without re-computation.

5. **Status cache needs explicit updates** — `delete_fov_config_entry()` does not call `update_fov_status_cache()`. The orchestration layer must handle this explicitly.

## Prevention Strategies

- When adding new assignment/linking operations, always design the corresponding unlink operation with cleanup
- Test with multiple FOVs sharing an entity to verify data isolation
- Verify auto-config behavior when testing config entry counts
- Use SQL queries (not just API calls) to verify data cleanup in tests

## Related Documents

- `docs/solutions/database-issues/zarr-sqlite-state-mismatch-re-thresholding.md` — Write-Invalidate-Cleanup pattern for dual-store consistency
- `docs/solutions/logic-errors/combined-mask-overwrites-last-group-threshold.md` — Verify data with SQL, not visual inspection
- `docs/solutions/architecture-decisions/run-scoped-architecture-refactor-learnings.md` — fov_config as the assignment layer
- `docs/solutions/architecture-decisions/layer-based-architecture-redesign-learnings.md` — Global layers composed per-FOV via fov_config

## Files Modified

- `src/percell3/core/queries.py` — 3 new query functions (~60 lines)
- `src/percell3/core/experiment_store.py` — 2 new store methods (~100 lines)
- `src/percell3/cli/menu.py` — Updated manage menus + descriptions (~120 lines)
- `tests/test_core/test_unassign.py` — New test file (331 lines, 15 tests)
