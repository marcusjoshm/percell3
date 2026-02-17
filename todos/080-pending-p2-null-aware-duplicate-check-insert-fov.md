---
status: pending
priority: p2
issue_id: "080"
tags: [plan-review, security, data-integrity]
dependencies: []
---

# insert_fov() Needs NULL-Aware Duplicate Check for SQLite UNIQUE Constraint

## Problem Statement

SQLite treats NULLs as distinct in UNIQUE constraints. The new `UNIQUE(name, bio_rep_id, condition_id, timepoint_id)` constraint won't prevent duplicate FOVs when `timepoint_id` is NULL. The current code has a manual NULL-aware check that must be extended.

## Findings

- **Security sentinel**: "The current code handles this at queries.py lines 191-204 with IS NULL check. The new insert_fov() must replicate this pattern including bio_rep_id."
- **Architecture strategist**: Confirmed this as an important implementation detail that is easy to miss.

## Proposed Solutions

### A) Extend existing NULL-aware pattern to include bio_rep_id

Copy the existing `insert_region()` NULL-aware duplicate check pattern. Extend the WHERE clause to include `bio_rep_id IS ?` with proper NULL handling. Test with NULL `timepoint_id` explicitly.

- **Pros**: Proven pattern, handles all NULL combinations correctly.
- **Cons**: Verbose SQL with IS NULL / = ? branching.
- **Effort**: Small.
- **Risk**: Low.

## Technical Details

Current pattern in `queries.py` lines 191-204 for `insert_region()`:
```python
# Check for duplicate with NULL-aware comparison
cursor.execute("""
    SELECT region_id FROM regions
    WHERE name = ?
    AND condition_id = ?
    AND (timepoint_id IS ? OR (timepoint_id IS NULL AND ? IS NULL))
""", (name, condition_id, timepoint_id, timepoint_id))
```

New `insert_fov()` must handle the full tuple:
```python
cursor.execute("""
    SELECT fov_id FROM fovs
    WHERE name = ?
    AND condition_id = ?
    AND (bio_rep_id IS ? OR (bio_rep_id IS NULL AND ? IS NULL))
    AND (timepoint_id IS ? OR (timepoint_id IS NULL AND ? IS NULL))
""", (name, condition_id, bio_rep_id, bio_rep_id, timepoint_id, timepoint_id))
```

Note: SQLite's `IS` operator is NULL-safe (`NULL IS NULL` returns true, `1 IS NULL` returns false), so `column IS ?` works correctly for both NULL and non-NULL parameter values. The `OR` fallback may not be needed if using `IS` consistently, but the defensive pattern is safer.

Affected files:
- `src/percell3/core/queries.py` — `insert_fov()` implementation
- `tests/test_core/` — duplicate detection tests

## Acceptance Criteria

- [ ] `insert_fov()` has NULL-aware duplicate check including bio_rep_id
- [ ] Test: two FOVs with same `(name, bio_rep, condition, NULL timepoint)` raises DuplicateError
- [ ] Test: two FOVs with same `(name, NULL bio_rep, condition, NULL timepoint)` raises DuplicateError
- [ ] Test: FOVs with different bio_rep_id but same name/condition/timepoint are allowed

## Work Log

- 2026-02-17 — Identified by security sentinel during plan review. Confirmed by architecture strategist.

## Resources

- Plan: docs/plans/2026-02-17-feat-data-model-bio-rep-fov-restructure-plan.md
- Existing pattern: src/percell3/core/queries.py lines 191-204
