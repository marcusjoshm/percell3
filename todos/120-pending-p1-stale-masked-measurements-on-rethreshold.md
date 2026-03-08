---
status: pending
priority: p1
issue_id: "120"
tags: [code-review, schema, data-integrity, stale-data]
dependencies: []
---

# Stale mask_inside/mask_outside measurements not cleaned on re-threshold

## Problem Statement

When a user re-thresholds a FOV+channel, `write_mask()` now cleans stale particles and particle summary metrics. However, `mask_inside` and `mask_outside` scoped measurements (written by plugins like `local_bg_subtraction` and `split_halo_condensate_analysis`) are NOT cleaned up. These measurements reference the old particle geometry and become stale when the threshold mask changes.

## Findings

- **Found by:** data-integrity-guardian, architecture-strategist
- `write_mask()` calls `delete_stale_particles_for_fov_channel()` which deletes particles + particle summary metrics
- But measurements with `scope IN ('mask_inside', 'mask_outside')` are left untouched
- These measurements were computed against the OLD threshold mask
- Re-running the plugin will INSERT OR REPLACE (due to UNIQUE constraint) but old metrics from a plugin that is NOT re-run will persist as stale
- Could lead to misleading analysis results if user exports without re-running all plugins

## Proposed Solutions

### Solution A: Delete scoped measurements in write_mask cleanup (Recommended)

Extend `delete_stale_particles_for_fov_channel` (or add a new function) to also delete `mask_inside` and `mask_outside` scoped measurements for the affected cells + channel.

**Pros:** Complete cleanup, prevents stale data
**Cons:** Slightly more aggressive — re-running plugins will need to recompute
**Effort:** Small
**Risk:** Low — the data needs to be recomputed anyway

### Solution B: Add a "dirty" flag to cells

Mark cells as needing recomputation when their threshold changes, and warn during export.

**Pros:** Non-destructive, user can decide
**Cons:** More complex, requires UI changes
**Effort:** Medium
**Risk:** Medium

## Acceptance Criteria

- [ ] Re-thresholding cleans `mask_inside` and `mask_outside` scoped measurements
- [ ] Plugin results are not stale after re-thresholding
- [ ] Add test verifying scoped measurement cleanup

## Technical Details

- **File:** `src/percell3/core/queries.py` — `delete_stale_particles_for_fov_channel()`
- **File:** `src/percell3/core/experiment_store.py` — `write_mask()`
- **Scope values:** `'mask_inside'`, `'mask_outside'` in measurements table
