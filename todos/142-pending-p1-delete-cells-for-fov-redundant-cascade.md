---
status: pending
priority: p1
issue_id: "142"
tags: [code-review, performance, sqlite]
---

# delete_cells_for_fov Has Redundant Manual DELETEs (CASCADE Handles It)

## Problem Statement
`queries.delete_cells_for_fov()` manually executes 3 DELETE statements (measurements, cell_tags, cells), but both `measurements` and `cell_tags` have `ON DELETE CASCADE` on `cell_id`. The manual deletes are entirely redundant, tripling the SQL work.

## Findings
- **File:** `src/percell3/core/queries.py:1235-1258`
- Found by: performance-oracle (CRITICAL-3), security-sentinel (F3)
- **Verified:** 2026-03-08 — issue still present
- Schema confirms: `cell_id INTEGER NOT NULL REFERENCES cells(id) ON DELETE CASCADE` on both `measurements` and `cell_tags` tables
- Current code at lines 1246-1256 still has 3 DELETE statements:
  1. `DELETE FROM measurements WHERE cell_id IN (SELECT id FROM cells WHERE fov_id = ?)`
  2. `DELETE FROM cell_tags WHERE cell_id IN (SELECT id FROM cells WHERE fov_id = ?)`
  3. `DELETE FROM cells WHERE fov_id = ?`
- Called from `experiment_store.py:639`, `auto_measure.py:195`, `roi_import.py:40`

## Proposed Solutions
1. **Remove redundant deletes** — Keep only `DELETE FROM cells WHERE fov_id = ?`. Let CASCADE handle measurements and cell_tags.

## Acceptance Criteria
- [ ] Only 1 DELETE statement instead of 3
- [ ] CASCADE correctly cleans up measurements and cell_tags
- [ ] Existing tests pass
