---
status: complete
priority: p1
issue_id: "113"
tags: [code-review, core, sql, bug]
dependencies: []
---

# SQL bind parameter limit crash for experiments with 1000+ cells

## Problem Statement

`select_group_tags_for_cells()` builds an `IN (?,?,?...)` clause with one placeholder per cell_id. SQLite has a default limit of 999 bind parameters. For experiments with 1000+ cells (common — a typical experiment has 5,000-50,000 cells), this will crash with `sqlite3.OperationalError`.

The query is called from `get_cell_group_tags()` which receives the full experiment cell list from `get_measurement_pivot()`.

## Findings

- **Found by:** performance-oracle
- **Location:** `src/percell3/core/queries.py:1205-1222`
- Same pattern exists in other queries but those typically receive smaller lists (per-FOV cell IDs or tag IDs)
- This is the first query where the full experiment cell list is routinely passed

## Proposed Solutions

### Solution A: Batch the query (Recommended)
```python
BATCH_SIZE = 900
all_rows = []
for i in range(0, len(cell_ids), BATCH_SIZE):
    batch = cell_ids[i:i + BATCH_SIZE]
    placeholders = ",".join("?" * len(batch))
    rows = conn.execute(f"... IN ({placeholders}) ...", batch).fetchall()
    all_rows.extend(rows)
return all_rows
```
- **Effort:** Small | **Risk:** Low

### Solution B: Use temporary table
- Insert cell_ids into a temp table, join instead of IN clause
- More efficient for very large lists but more complex
- **Effort:** Medium | **Risk:** Low

## Acceptance Criteria

- [ ] Query works with 5,000+ cell_ids
- [ ] Test with >999 cell IDs
- [ ] No performance regression for small experiments

## Work Log

- 2026-02-25: Identified during code review
