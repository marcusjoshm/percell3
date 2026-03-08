---
status: pending
priority: p2
issue_id: "126"
tags: [code-review, schema, data-integrity]
dependencies: []
---

# Missing ON DELETE CASCADE on most foreign keys

## Problem Statement

Only 3 of 15+ foreign key relationships in the schema have `ON DELETE CASCADE`. The rest require manual cascade deletion which is error-prone and has already caused stale data bugs (e.g., stale particles after re-thresholding).

## Findings

- **Found by:** data-integrity-guardian
- Tables with CASCADE: `fov_conditions`, `fov_status_cache`, `measurements` (on cell_id)
- Tables WITHOUT CASCADE: `cells.fov_id`, `cells.segmentation_run_id`, `particles.cell_id`, `particles.threshold_run_id`, `threshold_runs.channel_id`, `segmentation_runs.channel_id`, `analysis_runs.channel_id`, `group_tags.cell_id`, etc.
- Manual cascade deletion in `delete_fov()` and `delete_stale_particles_for_fov_channel()` must be kept in sync with schema changes
- SQLite requires `PRAGMA foreign_keys = ON` for CASCADE to work (already enabled in ExperimentStore)

## Proposed Solutions

### Solution A: Add CASCADE to critical FKs incrementally (Recommended)

Add `ON DELETE CASCADE` to the most important FKs first: `cells.fov_id`, `particles.cell_id`, `particles.threshold_run_id`. This reduces the manual cascade code needed.

**Pros:** Reduces bug surface, incremental
**Cons:** Schema migration, need to verify PRAGMA is always on
**Effort:** Medium
**Risk:** Low-Medium — need to test CASCADE behavior carefully

### Solution B: Full CASCADE migration

Add CASCADE to all FKs at once.

**Pros:** Complete solution
**Cons:** Large migration, higher risk
**Effort:** Large
**Risk:** Medium

## Acceptance Criteria

- [ ] Critical FKs have ON DELETE CASCADE
- [ ] Manual cascade code simplified or removed
- [ ] PRAGMA foreign_keys = ON verified in all connection paths

## Technical Details

- **File:** `src/percell3/core/schema.py` — FK definitions
- **File:** `src/percell3/core/queries.py` — manual cascade functions
