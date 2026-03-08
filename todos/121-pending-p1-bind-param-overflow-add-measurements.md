---
status: pending
priority: p1
issue_id: "121"
tags: [code-review, schema, performance, crash]
dependencies: []
---

# add_measurements crashes with >999 cells per FOV (bind parameter overflow)

## Problem Statement

`add_measurements()` in `queries.py` builds SQL `IN (?)` clauses that can exceed SQLite's 999 bind-parameter limit when a FOV has more than ~1000 cells. This will cause a hard crash during measurement operations on dense FOVs.

## Findings

- **Found by:** performance-oracle, kieran-python-reviewer
- SQLite has a compile-time limit of 999 bind parameters (SQLITE_MAX_VARIABLE_NUMBER)
- `add_measurements` and `select_measurements` build `IN (?)` clauses from cell_id lists without batching
- `delete_stale_particles_for_fov_channel` already has batching (batch_size=900) but the old_run_ids list is NOT batched
- Real-world experiments can have 1000+ cells per FOV in confluent cultures
- Past solution `docs/solutions/` already documents this as a known pattern (todo 003)

## Proposed Solutions

### Solution A: Add batch_size guard to all IN-clause builders (Recommended)

Apply the same batching pattern used in `delete_stale_particles_for_fov_channel` to `add_measurements`, `select_measurements`, and any other query that builds IN clauses from variable-length lists.

**Pros:** Consistent pattern, prevents crashes
**Cons:** Slightly more complex query code
**Effort:** Medium
**Risk:** Low

### Solution B: Use temporary tables for large IN clauses

Insert IDs into a temp table, then JOIN instead of IN.

**Pros:** Cleaner SQL, no batching needed
**Cons:** More refactoring, temp table overhead
**Effort:** Medium
**Risk:** Low

## Acceptance Criteria

- [ ] No crash with 1000+ cell FOVs
- [ ] All IN-clause builders use batching or temp tables
- [ ] Add test with >999 cell IDs to verify

## Technical Details

- **File:** `src/percell3/core/queries.py` — `add_measurements()`, `select_measurements()`
- **SQLite limit:** SQLITE_MAX_VARIABLE_NUMBER = 999
- **Related:** todo 003 (previously fixed for empty list case)
