---
status: pending
priority: p1
issue_id: "003"
tags: [code-review, quality]
dependencies: []
---
# Empty List Crashes in SQL IN Clauses

## Problem Statement

Several functions in `queries.py` dynamically build SQL `IN (...)` clauses from
Python lists. When an empty list is passed, the generated SQL contains `IN ()`,
which is syntactically invalid in SQLite and raises `sqlite3.OperationalError`.
This is a runtime crash triggered by a perfectly reasonable input (no items to
operate on).

## Findings

- `delete_cell_tags` (queries.py:573-583) builds `IN (...)` from `cell_ids`
  without checking for an empty list.
- `select_measurements` (queries.py:463-464) similarly interpolates a cell-ID
  list into an `IN` clause.
- `select_cells` (queries.py:396-398) has the same pattern.
- In all cases an empty list produces the SQL fragment `IN ()`, which SQLite
  rejects with `OperationalError: near ")": syntax error`.
- Callers have no way to distinguish this crash from a genuine database error.

## Proposed Solutions

### Option 1 -- Early-return guard (recommended)

Add an early return at the top of each affected function:

```python
if not cell_ids:
    return []  # or return, for void functions like delete_cell_tags
```

This is the simplest, most readable, and most efficient fix. An empty input
list logically means "nothing to do", so returning immediately is semantically
correct.

### Option 2 -- SQL builder helper with empty-list handling

Create a helper function `sql_in_clause(column: str, values: list)` that:
- Returns `("FALSE", [])` when `values` is empty (making the WHERE always fail).
- Returns `(f"{column} IN ({placeholders})", values)` otherwise.

This centralizes the logic and prevents future regressions in new query
functions, but adds indirection.

## Technical Details

- **Files affected:** `queries.py:573-583`, `queries.py:463-464`,
  `queries.py:396-398`
- **SQLite behaviour:** `IN ()` is not valid SQL per the SQLite grammar.
  There is no zero-element form of the IN operator.
- **Risk:** Very low. An early return for an empty list is a no-op by
  definition and cannot change behaviour for non-empty inputs.

## Acceptance Criteria

- [ ] `delete_cell_tags` returns immediately when `cell_ids` is empty.
- [ ] `select_measurements` returns an empty list when `cell_ids` is empty.
- [ ] `select_cells` returns an empty list when `cell_ids` is empty.
- [ ] Unit tests pass an empty list to each function and assert no exception
      is raised and the correct empty result is returned.
- [ ] Grep confirms no other `IN (...)` construction sites in queries.py lack
      an empty-list guard.

## Work Log

### 2026-02-12 - Code Review Discovery

Identified during manual review of `percell3.core`. Multiple query functions
crash on empty list input due to invalid SQL generation. Classified as
P1/quality because it causes unhandled runtime exceptions on valid input.
