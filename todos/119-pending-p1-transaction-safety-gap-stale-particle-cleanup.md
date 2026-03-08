---
status: pending
priority: p1
issue_id: "119"
tags: [code-review, schema, data-integrity, transaction-safety]
dependencies: []
---

# Transaction safety gap in delete_stale_particles_for_fov_channel

## Problem Statement

`delete_stale_particles_for_fov_channel()` in `queries.py` conditionally commits only when `total_deleted > 0`, but the measurement deletion block runs unconditionally. If particles were already deleted but summary measurements still exist, the measurement DELETE executes but `conn.commit()` is never called — leaving the transaction uncommitted.

## Findings

- **Found by:** kieran-python-reviewer, data-integrity-guardian
- `queries.py:delete_stale_particles_for_fov_channel` — commit on line is conditional on `total_deleted > 0`
- The measurement cleanup block always runs regardless of `total_deleted`
- If no stale particles exist but stale measurements do, those deletes are never committed
- Also: if `old_run_ids` list exceeds ~900 items, the IN clause could hit SQLite's 999 bind-parameter limit

## Proposed Solutions

### Solution A: Always commit after any DELETE (Recommended)

Track whether any rows were affected (particles OR measurements) and commit if either changed. Or simply always commit at the end.

**Pros:** Simple, correct, no partial-commit risk
**Cons:** Extra commit call if nothing changed (negligible cost)
**Effort:** Small
**Risk:** Low

### Solution B: Use a single transaction context manager

Wrap the entire function in a `BEGIN`/`COMMIT` pair so all deletes are atomic.

**Pros:** Atomic, clean
**Cons:** Slightly more refactoring
**Effort:** Small
**Risk:** Low

## Acceptance Criteria

- [ ] Measurement deletions are always committed
- [ ] No partial-commit scenario possible
- [ ] Existing tests still pass
- [ ] Add test: stale measurements without stale particles are still cleaned

## Technical Details

- **File:** `src/percell3/core/queries.py` — `delete_stale_particles_for_fov_channel()`
- **File:** `tests/test_core/test_experiment_store.py` — `TestWriteMaskCleansStaleParticles`
