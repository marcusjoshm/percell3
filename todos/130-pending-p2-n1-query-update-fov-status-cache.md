---
status: pending
priority: p2
issue_id: "130"
tags: [code-review, performance]
dependencies: []
---

# update_fov_status_cache has N+1 query amplification

## Problem Statement

`update_fov_status_cache()` executes one query per FOV to compute status. When called in a loop (e.g., after batch operations), this becomes an N+1 query pattern that scales poorly with experiment size.

## Findings

- **Found by:** performance-oracle
- Currently called per-FOV after segmentation, thresholding, measurement
- For experiments with 100+ FOVs, batch operations trigger 100+ individual cache update queries
- Each update query itself may do multiple subqueries (count cells, count particles, etc.)

## Proposed Solutions

### Solution A: Add batch update_fov_status_cache (Recommended)

Create `update_fov_status_cache_batch(fov_ids)` that computes status for multiple FOVs in a single query.

**Pros:** O(1) queries instead of O(N)
**Cons:** More complex SQL
**Effort:** Small-Medium
**Risk:** Low

## Acceptance Criteria

- [ ] Batch cache update available
- [ ] Callers use batch version where possible
- [ ] No performance regression for single-FOV case

## Technical Details

- **File:** `src/percell3/core/queries.py` — `update_fov_status_cache()`
