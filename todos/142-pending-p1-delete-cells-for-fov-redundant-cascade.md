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
- **File:** `src/percell3/core/queries.py:1084-1107`
- Found by: performance-oracle (CRITICAL-3), security-sentinel (F3)
- Schema confirms: `cell_id INTEGER NOT NULL REFERENCES cells(id) ON DELETE CASCADE` on both tables

## Proposed Solutions
1. **Remove redundant deletes** — Keep only `DELETE FROM cells WHERE fov_id = ?`. Let CASCADE handle measurements and cell_tags.

## Acceptance Criteria
- [ ] Only 1 DELETE statement instead of 3
- [ ] CASCADE correctly cleans up measurements and cell_tags
- [ ] Existing tests pass
