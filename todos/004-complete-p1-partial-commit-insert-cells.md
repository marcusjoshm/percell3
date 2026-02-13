---
status: pending
priority: p1
issue_id: "004"
tags: [code-review, quality]
dependencies: []
---
# Partial Commit on Cell Insert Failure

## Problem Statement

`insert_cells` in `queries.py` performs row-by-row INSERT operations inside a
loop and issues a single commit at the end. If a `DuplicateError` is raised
mid-loop (e.g., on a duplicate cell ID), all preceding inserts remain in an
uncommitted transaction with no rollback. The database connection is left in an
ambiguous state -- the partial inserts are neither committed nor rolled back,
and subsequent operations on the same connection may behave unpredictably.

## Findings

- `insert_cells` (queries.py:329-350) iterates over a list of cell objects
  and inserts each one individually.
- A single `conn.commit()` is called after the loop completes.
- If a `DuplicateError` (or any other exception) is raised during an insert,
  execution jumps out of the loop and the commit is never reached.
- There is no `try/except/finally` block and no `conn.rollback()` call.
- The partial transaction lingers on the connection, meaning the next
  `conn.commit()` from an unrelated operation could inadvertently commit the
  partial cell inserts.
- This violates atomicity: either all cells should be inserted or none.

## Proposed Solutions

### Option 1 -- try/except with explicit rollback (recommended)

Wrap the loop in a try/except block:

```python
def insert_cells(conn, cells):
    try:
        for cell in cells:
            _insert_one_cell(conn, cell)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
```

This guarantees atomicity: all inserts succeed and are committed, or none are
persisted.

### Option 2 -- Use `executemany` with a single statement

Replace the row-by-row loop with `cursor.executemany(sql, params_list)`. This
is both faster (fewer round-trips) and naturally atomic within a single
transaction. The commit/rollback wrapper is still needed for safety, but the
single-statement approach reduces the window for partial failure.

## Technical Details

- **Files affected:** `queries.py:329-350`
- **SQLite transaction semantics:** In autocommit=False mode (Python sqlite3
  default when DML is issued), an uncommitted transaction remains open until
  an explicit `commit()` or `rollback()`. If neither is called, the
  transaction is rolled back when the connection is closed -- but relying on
  this is fragile and leaves the connection dirty for any intervening
  operations.
- **`executemany` performance:** For large cell lists (thousands of cells per
  region is common in microscopy), `executemany` can be 5-10x faster than
  individual inserts due to reduced Python-level overhead.

## Acceptance Criteria

- [ ] `insert_cells` wraps its database operations in try/except with
      `conn.rollback()` on failure.
- [ ] After a failed insert (e.g., duplicate cell ID), no partial rows are
      committed to the database.
- [ ] After a failed insert, the connection is in a clean state (no lingering
      open transaction).
- [ ] Unit test inserts a batch containing a known duplicate, asserts
      `DuplicateError` is raised, and verifies zero rows were persisted.
- [ ] Consider migrating to `executemany` for performance (can be a follow-up).

## Work Log

### 2026-02-12 - Code Review Discovery

Identified during manual review of `percell3.core`. The `insert_cells` function
lacks rollback handling, leaving the database in an ambiguous state on partial
failure. Classified as P1/quality because it violates transactional atomicity
and can silently corrupt experiment data.
