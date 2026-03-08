---
status: pending
priority: p2
issue_id: "126"
tags: [code-review, schema, data-integrity]
dependencies: []
---

# Missing ON DELETE CASCADE on 5 remaining foreign keys

## Problem Statement

Most foreign keys now have `ON DELETE CASCADE` or `ON DELETE SET NULL`, but 5 FKs still have no ON DELETE clause. These are reference-type relationships where cascade deletion may not be appropriate, but the lack of explicit policy means SQLite's default RESTRICT behavior applies, which could block legitimate deletions.

## Findings

- **Found by:** data-integrity-guardian
- **Verified:** 2026-03-08 — schema substantially improved since original audit

### FKs WITH explicit ON DELETE (18 total — all good):
All critical data FKs now have CASCADE or SET NULL, including `cells.fov_id`, `cells.segmentation_id`, `measurements.cell_id`, `particles.fov_id`, `particles.threshold_id`, `cell_tags.cell_id`, `fov_tags.*`, `fov_status_cache.fov_id`, `fov_config.*`, `analysis_config.experiment_id`, `segmentations.source_fov_id` (SET NULL), `thresholds.source_fov_id` (SET NULL).

### FKs WITHOUT ON DELETE (5 remaining):
1. `fovs.condition_id -> conditions(id)` — no ON DELETE (RESTRICT by default)
2. `fovs.bio_rep_id -> bio_reps(id)` — no ON DELETE (RESTRICT by default)
3. `fovs.timepoint_id -> timepoints(id)` — no ON DELETE (RESTRICT by default)
4. `measurements.channel_id -> channels(id)` — no ON DELETE (RESTRICT by default)
5. `cell_tags.tag_id -> tags(id)` — no ON DELETE (RESTRICT by default)

**Note:** These 5 are arguably correct as RESTRICT — deleting a condition/bio_rep/timepoint/channel/tag should probably be blocked if data references it. However, the policy should be made explicit.

- `delete_stale_particles_for_fov_channel()` has been removed; replaced with simpler `delete_particles_for_fov()`, `delete_particles_for_threshold()`, `delete_particles_for_fov_threshold()`
- `delete_cells_for_fov()` still has redundant manual cascade DELETEs (see todo 142)

## Proposed Solutions

### Solution A: Make RESTRICT explicit on remaining 5 FKs (Recommended)

Add explicit `ON DELETE RESTRICT` to the 5 remaining FKs for clarity and self-documentation.

**Pros:** Self-documenting, no behavioral change
**Cons:** Schema migration (minor)
**Effort:** Small
**Risk:** Very Low

### Solution B: Add CASCADE to `cell_tags.tag_id`

The one FK where CASCADE might be preferable — deleting a tag should remove its associations.

**Pros:** Allows clean tag deletion
**Cons:** Schema migration
**Effort:** Small
**Risk:** Low

## Acceptance Criteria

- [ ] All 5 remaining FKs have explicit ON DELETE policy
- [ ] `delete_cells_for_fov()` redundant manual cascade removed (see todo 142)
- [ ] PRAGMA foreign_keys = ON verified in all connection paths (already done)

## Technical Details

- **File:** `src/percell3/core/schema.py` — FK definitions (lines 56-58, 116, 184)
