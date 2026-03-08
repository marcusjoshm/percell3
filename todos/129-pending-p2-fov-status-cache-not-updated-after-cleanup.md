---
status: pending
priority: p2
issue_id: "129"
tags: [code-review, schema, data-integrity, performance]
dependencies: []
---

# fov_status_cache not updated after write_mask particle cleanup

## Problem Statement

`write_mask()` calls `delete_stale_particles_for_fov_channel()` which may delete particles and measurements, but the `fov_status_cache` is not updated afterward. The cache may show stale particle counts or "measured" status for FOVs that no longer have those measurements.

## Findings

- **Found by:** performance-oracle, data-integrity-guardian
- `fov_status_cache` stores: `has_cells, has_particles, has_measurements, measurement_count`
- `update_fov_status_cache()` is called in various places but NOT after `write_mask()` cleanup
- After cleanup, `has_particles` may be True but the FOV has no particles
- Cache is used by the CLI menu to show FOV status — stale cache shows incorrect info
- `update_fov_status_cache` also has an N+1 query pattern (one query per FOV)

## Proposed Solutions

### Solution A: Call update_fov_status_cache after write_mask cleanup (Recommended)

Add a call to `update_fov_status_cache(fov_id)` at the end of `write_mask()` when particles were deleted.

**Pros:** Simple, correct
**Cons:** Extra query per write_mask call
**Effort:** Small
**Risk:** Low

## Acceptance Criteria

- [ ] `fov_status_cache` is updated after particle cleanup in `write_mask()`
- [ ] CLI menu shows correct status after re-thresholding

## Technical Details

- **File:** `src/percell3/core/experiment_store.py` — `write_mask()`
- **File:** `src/percell3/core/queries.py` — `update_fov_status_cache()`
