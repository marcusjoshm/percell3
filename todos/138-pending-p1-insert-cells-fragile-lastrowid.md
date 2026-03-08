---
status: pending
priority: p1
issue_id: "138"
tags: [code-review, data-integrity, sqlite]
---

# insert_cells Fragile lastrowid Assumption

## Problem Statement
`queries.insert_cells()` uses `last_insert_rowid()` after `executemany` and assumes contiguous IDs via `range(last_id - len(cells) + 1, last_id + 1)`. SQLite does not guarantee contiguous IDs when rows have been previously deleted. This returns incorrect cell IDs for all cells except the last one, leading to silent data corruption when those IDs are used for measurements, tags, or other references.

## Findings
- **File:** `src/percell3/core/queries.py:627-628`
- Found by: kieran-python-reviewer (C1), security-sentinel (F1)
- The fragile ID assumption is a known SQLite anti-pattern

## Proposed Solutions
1. **Use individual inserts collecting lastrowid** — Loop with `cursor.execute()` per cell, collect `cursor.lastrowid`. Pros: Simple, correct. Cons: Slightly slower for large batches.
2. **Use INSERT ... RETURNING id** — Available SQLite 3.35+ (Python 3.10+ bundles this). Pros: Single statement, correct. Cons: Requires fetchall after executemany.
3. **Wrap in BEGIN IMMEDIATE + query back** — Keep executemany but query `SELECT id FROM cells WHERE fov_id=? AND segmentation_id=? ORDER BY id` after. Pros: Batch performance. Cons: Extra query.

## Acceptance Criteria
- [ ] Cell IDs returned by `insert_cells` are always correct, even after deletions
- [ ] Existing tests pass
