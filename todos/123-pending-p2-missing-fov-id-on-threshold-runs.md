---
status: resolved-by-refactor
priority: p2
issue_id: "123"
tags: [code-review, schema, architecture]
dependencies: []
---

> **Resolved by layer-based architecture redesign (2026-03-02).** The `threshold_runs` table no longer exists in the codebase; it was replaced by `thresholds` with a `source_fov_id` column.

# threshold_runs table missing fov_id column

## Problem Statement

The `threshold_runs` table has no `fov_id` column, making per-FOV queries on threshold runs require multi-table joins through `particles → cells → fovs`. This complicates cleanup queries, makes the schema harder to reason about, and increases the risk of bugs in functions like `delete_stale_particles_for_fov_channel`.

## Findings

- **Found by:** architecture-strategist, data-integrity-guardian, kieran-python-reviewer
- `threshold_runs` schema: `id, channel_id, method, parameters, threshold_value, created_at`
- To find threshold runs for a specific FOV, you must join: `threshold_runs → particles → cells → fovs`
- `delete_stale_particles_for_fov_channel` currently works around this by querying cells for the FOV, then particles for those cells
- Adding `fov_id` would simplify: `SELECT * FROM threshold_runs WHERE fov_id = ? AND channel_id = ?`
- `menu.py:_threshold_fov()` already knows the fov_id when creating threshold runs

## Proposed Solutions

### Solution A: Add fov_id FK to threshold_runs (Recommended)

Add `fov_id INTEGER NOT NULL REFERENCES fovs(id)` to the `threshold_runs` table. Update `add_threshold_run()` to accept and store fov_id.

**Pros:** Clean queries, matches data model reality, simplifies cleanup
**Cons:** Schema migration needed
**Effort:** Medium
**Risk:** Low — additive change

### Solution B: Create a junction table

Create `fov_threshold_runs(fov_id, threshold_run_id)` to track the relationship.

**Pros:** Doesn't modify existing table
**Cons:** Over-engineered for a 1:N relationship
**Effort:** Medium
**Risk:** Low

## Acceptance Criteria

- [ ] `threshold_runs` has `fov_id` column
- [ ] `add_threshold_run()` stores fov_id
- [ ] Cleanup queries simplified to use fov_id directly
- [ ] Existing data migration handles NULL for legacy rows

## Technical Details

- **File:** `src/percell3/core/schema.py` — `threshold_runs` DDL
- **File:** `src/percell3/core/queries.py` — `add_threshold_run()`, `delete_stale_particles_for_fov_channel()`
- **File:** `src/percell3/cli/menu.py` — `_threshold_fov()`
