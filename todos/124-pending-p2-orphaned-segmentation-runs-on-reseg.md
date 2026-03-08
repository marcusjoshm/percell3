---
status: resolved-by-refactor
priority: p2
issue_id: "124"
tags: [code-review, schema, data-integrity, stale-data]
dependencies: []
---

> **Resolved by layer-based architecture redesign (2026-03-02).** The `segmentation_runs` table no longer exists in the codebase; segmentations are now global entities with CASCADE deletes, preventing orphaned rows.

# Orphaned segmentation_runs accumulate after re-segmentation

## Problem Statement

When a FOV is re-segmented, a new `segmentation_runs` row is created and old cells are deleted, but the old `segmentation_runs` row remains. Over multiple re-segmentation cycles, orphaned rows accumulate with no cells referencing them.

## Findings

- **Found by:** data-integrity-guardian, architecture-strategist
- `cells` table has `segmentation_run_id` FK but no CASCADE
- Re-segmentation creates new cells with new run_id, deletes old cells
- Old `segmentation_runs` row is never deleted
- Similarly, old `threshold_runs` rows accumulate (particles deleted but run row stays)
- `analysis_runs` table has the same pattern — rows accumulate without cleanup

## Proposed Solutions

### Solution A: Delete old run rows when re-running (Recommended)

When inserting a new segmentation/threshold/analysis run for a FOV+channel, delete the previous run row(s) that have no remaining child records.

**Pros:** Clean database, no orphaned rows
**Cons:** Need to check for children before deleting
**Effort:** Small
**Risk:** Low

### Solution B: Add ON DELETE CASCADE and delete from parent

Add CASCADE to the FKs, then delete the old run row which cascades to children.

**Pros:** Atomic cleanup via CASCADE
**Cons:** Major schema change, risky if done wrong
**Effort:** Medium
**Risk:** Medium

## Acceptance Criteria

- [ ] Re-segmentation removes old segmentation_runs row
- [ ] Re-thresholding removes old threshold_runs row
- [ ] No orphaned run rows accumulate
- [ ] Add test verifying cleanup

## Technical Details

- **File:** `src/percell3/core/schema.py` — `segmentation_runs`, `threshold_runs`, `analysis_runs`
- **File:** `src/percell3/core/queries.py` — run insertion functions
