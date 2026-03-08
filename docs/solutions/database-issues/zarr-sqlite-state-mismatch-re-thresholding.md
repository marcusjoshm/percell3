---
title: "Stale Particles After Re-thresholding: Zarr/SQLite State Mismatch"
date: 2026-02-27
category: database-issues
tags:
  - particles
  - thresholding
  - csv-export
  - data-consistency
  - zarr
  - sqlite
  - dual-store
severity: high
modules:
  - core
symptoms:
  - "Most particles show 0 intensity in CSV export after re-thresholding"
  - "Only particles from the current threshold run have correct values"
root_cause: |
  masks.zarr stores ONE mask per FOV+channel (overwritten on re-threshold),
  but the particles table accumulated rows from ALL threshold runs. During
  CSV export, old particle positions no longer matched the new mask.
solution_summary: |
  Added delete_stale_particles_for_fov_channel() to queries.py and called
  it from write_mask() in experiment_store.py. When a new mask is written,
  old particles and summary measurements from previous threshold runs are
  automatically deleted.
---

# Stale Particles After Re-thresholding: Zarr/SQLite State Mismatch

## Problem

When re-thresholding a FOV+channel in PerCell 3, the mask file (`masks.zarr`) was overwritten with new particle locations, but old particle records remained in SQLite. During CSV export, `_add_particle_channel_intensities()` reconstructed particle masks using the new mask, but old particles referenced positions that no longer existed, resulting in 0 intensity for most particles in the final output.

## Investigation Steps

1. Noticed most particles had 0 intensity in exported CSV from a real experiment
2. Queried the `particles` table — found cell 13 had 58 particles from old threshold run 9 and only 2 from current run 16
3. Loaded the mask from disk — only 1,312 non-zero pixels (consistent with run 16)
4. Checked particle bbox locations from run 9 against the current mask — all had 0 mask pixels at those positions
5. Verified run 16 particle locations matched perfectly (60 and 33 pixels respectively)
6. Confirmed root cause: `masks.zarr` was overwritten on each threshold run, but old particle records were never deleted

## Root Cause

The `masks.zarr` file stores a single mask per FOV+channel and is overwritten during each threshold operation. However, the `particles` table in SQLite accumulated rows from all threshold runs without any cleanup mechanism. When `_add_particle_channel_intensities()` attempted to reconstruct particle intensities during CSV export, it loaded the current mask but tried to match it against particle bbox/centroid locations from previous runs — which no longer existed in the new mask — resulting in zero-pixel matches and zero intensities.

This is a **dual-store consistency** problem: two storage backends (Zarr for images, SQLite for metadata) can become desynchronized when one is updated without cleaning the other.

## Solution

### 1. Added cleanup function to `queries.py`

```python
def delete_stale_particles_for_fov_channel(
    conn: sqlite3.Connection,
    fov_id: int,
    channel_id: int,
    keep_run_id: int,
) -> int:
```

This function:
- Finds all `threshold_run` IDs for the channel except `keep_run_id`
- Finds all cells belonging to the FOV
- Batch-deletes particles from old runs (batch_size=900 to avoid SQLite bind param limit)
- Deletes particle summary measurements (`particle_count`, `total_particle_area`, etc.)

### 2. Modified `write_mask()` in `experiment_store.py`

```python
def write_mask(self, fov_id, channel, mask, threshold_run_id):
    ch = self.get_channel(channel)
    deleted = queries.delete_stale_particles_for_fov_channel(
        self._conn, fov_id, ch.id, keep_run_id=threshold_run_id,
    )
    if deleted > 0:
        logger.info("Cleaned up %d stale particles for FOV %d channel %s",
                     deleted, fov_id, channel)
    # ... write the new mask to zarr ...
```

### 3. Added tests

Three tests in `TestWriteMaskCleansStaleParticles`:
- **Particles deleted:** Old threshold run particles are removed
- **Measurements deleted:** Particle summary measurements are removed
- **Other FOV preserved:** Particles from other FOVs are not affected

## Verification

- All 1003 existing tests pass
- 3 new targeted tests verify cleanup behavior
- Tested against real experiment data at `/Volumes/NX-01-A/PerCell3_analysis/Dcp2-Dcp1A_sensor_original`

## Prevention Strategies

### 1. Enforce Store Mutation Discipline

**Core Principle:** Zarr and SQLite mutations must always be paired at the logical operation level.

Never split Zarr writes and SQLite writes across multiple functions. A single high-level ExperimentStore method should own both the Zarr write and the SQLite cleanup. Example: `write_mask()` now handles both.

### 2. Adopt a "Write-Invalidate-Cleanup" Pattern

On re-operation, always clean up old state completely before creating new state:
1. Identify stale data in BOTH stores
2. Delete from both stores atomically
3. Create new state after cleanup is committed

### 3. Use ON DELETE CASCADE Where Possible

The relational schema should express data dependencies. Adding `ON DELETE CASCADE` to critical FKs (e.g., `particles.cell_id`, `particles.threshold_run_id`) reduces the need for manual cascade deletion code.

### 4. Test Invariants, Not Just Happy Paths

Add invariant tests that verify cross-store consistency:
- Every `particle.cell_id` references an existing cell
- No `segmentation_runs` row has zero cells referencing it
- Every Zarr mask group has a corresponding `threshold_runs` record

## Design Principles for Dual-Store Consistency

1. **ExperimentStore is the single mutation authority** — all writes to Zarr or SQLite must go through it
2. **Separate read-only from mutation operations** — read queries can live in `queries.py`, but mutations live in ExperimentStore
3. **Zarr state must reflect SQLite ground truth** — if a SQLite record is deleted, related Zarr data must be cleaned too
4. **Make idempotence explicit** — all re-operation functions should be safe to call multiple times

## Known Remaining Gaps

The fix addresses the most visible symptom (stale particles), but the same pattern repeats:

| Todo | Issue | Priority |
|------|-------|----------|
| #119 | Transaction safety: conditional commit misses measurement deletes | P1 |
| #120 | Stale `mask_inside`/`mask_outside` measurements not cleaned | P1 |
| #121 | Bind parameter overflow with >999 cells | P1 |
| #122 | Layering violation: `queries.py` imports from `percell3.measure` | P1 |
| #123 | `threshold_runs` missing `fov_id` column | P2 |
| #124 | Orphaned `segmentation_runs` accumulate | P2 |
| #127 | Re-segmentation leaves stale Zarr masks | P2 |

## Related Documentation

- `docs/plans/2026-02-19-feat-thresholding-module-plan.md` — Original design specifying "delete old particles on re-threshold" (not fully implemented until this fix)
- `docs/brainstorms/2026-02-19-thresholding-module-brainstorm.md` — Design decision: "clean slate" re-thresholding pattern
- `docs/solutions/integration-issues/napari-viewer-datamodel-merge-api-conflicts.md` — Similar dual-store cascade issue during API renames
- `docs/solutions/logic-errors/segment-minimum-area-artifact-filtering.md` — Post-processing cleanup ordering
- `todos/113-complete-p1-sql-bind-param-limit-group-tags-query.md` — Prior fix for the same SQLite 999-parameter limit pattern
