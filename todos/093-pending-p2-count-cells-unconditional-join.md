---
status: pending
priority: p2
issue_id: "093"
tags: [code-review, performance, core, queries]
dependencies: []
---

# `count_cells` Unconditionally JOINs `fovs` Table

## Problem Statement

`count_cells()` in `queries.py` always JOINs `fovs`, even when no filter requires it. When called as `count_cells(conn, is_valid=True)` (the common case), the JOIN is pure overhead.

## Findings

- **Found by:** performance-oracle
- **Evidence:** `queries.py:489-512` — `SELECT COUNT(*) FROM cells c JOIN fovs f ON c.fov_id = f.id` is unconditional

## Proposed Solutions

### Solution A: Conditional JOIN (Recommended)
- Only JOIN fovs when `condition_id` or `bio_rep_id` filters are provided
- `fov_id` filter can use `c.fov_id` directly without JOIN
- **Effort:** Small | **Risk:** Low

## Acceptance Criteria

- [ ] JOIN only added when condition_id or bio_rep_id filters are present
- [ ] All existing tests pass

## Work Log

- 2026-02-17: Identified during code review
