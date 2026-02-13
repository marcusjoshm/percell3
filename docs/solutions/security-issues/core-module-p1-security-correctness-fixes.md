---
title: "Critical Security and Data Integrity Fixes in percell3.core"
date: 2026-02-12
category: security-issues
severity: P1
component: percell3.core
tags:
  - path-traversal
  - input-validation
  - exception-handling
  - transaction-integrity
  - sql-safety
  - data-corruption
status: resolved
related_modules:
  - percell3.core.experiment_store
  - percell3.core.queries
  - percell3.core.zarr_io
  - percell3.core.exceptions
problem_type:
  - security_vulnerability
  - incorrect_exception_type
  - sql_generation_bug
  - transaction_rollback_missing
---

# Critical Security and Data Integrity Fixes in percell3.core

## Problem

Four P1 (critical) bugs were discovered during a multi-agent code review of the `percell3.core` module. Together they represented a security vulnerability, two correctness bugs, and a data integrity hazard:

1. **Path traversal**: User-supplied names (condition, region, channel, timepoint) were interpolated directly into zarr filesystem paths with no validation, allowing directory escape
2. **Wrong exception type**: `select_condition_id()` raised `RegionNotFoundError` for missing conditions, breaking error handling semantics
3. **Empty list SQL crash**: Functions generating `IN ()` clauses crashed on empty lists with invalid SQL
4. **Partial commit**: `insert_cells()` had no rollback on failure, leaving the database in an inconsistent state

## Investigation

These issues were identified through a parallel multi-agent code review using six specialized reviewers (kieran-python-reviewer, code-simplicity-reviewer, security-sentinel, performance-oracle, agent-native-reviewer, learnings-researcher). The path traversal vulnerability was flagged independently by three agents (security-sentinel, kieran-python-reviewer, agent-native-reviewer), confirming its severity.

### What didn't work (before the fix)

**Path traversal example:**
```python
# zarr_io.py — no validation on inputs
def image_group_path(condition: str, region: str, timepoint=None):
    return f"{condition}/{region}"  # condition="../../etc" escapes the store

# experiment_store.py — names passed straight through
def add_region(self, name, condition, ...):
    gp = zarr_io.image_group_path(condition, name, timepoint)  # unvalidated
```

**Wrong exception:**
```python
# queries.py:132
def select_condition_id(conn, name):
    row = conn.execute("SELECT id FROM conditions WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise RegionNotFoundError(name)  # condition not found — wrong type!
```

**Empty list crash:**
```python
# queries.py — generates "IN ()" which is invalid SQL
placeholders = ",".join("?" * len([]))  # produces ""
conn.execute(f"DELETE FROM cell_tags WHERE cell_id IN ({placeholders})", ...)
```

**Partial commit:**
```python
# queries.py — no rollback on mid-loop failure
def insert_cells(conn, cells):
    ids = []
    for cell in cells:
        try:
            cur = conn.execute("INSERT INTO cells ...", (...))
            ids.append(cur.lastrowid)
        except sqlite3.IntegrityError:
            raise DuplicateError(...)  # earlier inserts left in limbo
    conn.commit()
```

## Solution

### Fix 1: Path Traversal — Centralized Name Validation

Added `_validate_name()` in `experiment_store.py`, called at all entry points where user-supplied names enter the system (`add_channel`, `add_condition`, `add_timepoint`, `add_region`):

```python
import re

_VALID_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")

def _validate_name(value: str, field: str = "name") -> str:
    if not value:
        raise ValueError(f"{field} must not be empty")
    if ".." in value:
        raise ValueError(f"{field} must not contain '..': {value!r}")
    if not _VALID_NAME_RE.match(value):
        raise ValueError(
            f"{field} contains invalid characters: {value!r}. "
            "Only alphanumeric, dots, hyphens, and underscores are allowed."
        )
    return value
```

Usage at entry points:
```python
def add_channel(self, name, ...):
    _validate_name(name, "channel name")
    # ...

def add_condition(self, name, ...):
    _validate_name(name, "condition name")
    # ...
```

### Fix 2: Correct Exception Type

Created `ConditionNotFoundError` in `exceptions.py`:

```python
class ConditionNotFoundError(ExperimentError):
    def __init__(self, name: str | None = None) -> None:
        msg = f"Condition not found: {name}" if name else "Condition not found"
        super().__init__(msg)
        self.name = name
```

Fixed `queries.py`:
```python
def select_condition_id(conn, name):
    row = conn.execute("SELECT id FROM conditions WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise ConditionNotFoundError(name)  # was: RegionNotFoundError
    return row["id"]
```

Exported from `core/__init__.py`.

### Fix 3: Empty List SQL Guards

Added early-return guards and explicit length checks:

```python
# delete_cell_tags — early return
def delete_cell_tags(conn, cell_ids, tag_id):
    if not cell_ids:
        return
    placeholders = ",".join("?" * len(cell_ids))
    # ...

# select_measurements — explicit check replaces truthiness
if cell_ids is not None and len(cell_ids) > 0:
    placeholders = ",".join("?" * len(cell_ids))
    clauses.append(f"m.cell_id IN ({placeholders})")
    params.extend(cell_ids)
```

Applied to: `delete_cell_tags`, `insert_cell_tags`, `select_measurements` (3 filter params), `select_cells` (tag_ids filter).

### Fix 4: Atomic Insert with Rollback

Wrapped the insert loop in try/except with explicit rollback:

```python
def insert_cells(conn, cells):
    if not cells:
        return []
    ids = []
    try:
        for cell in cells:
            cur = conn.execute("INSERT INTO cells ...", (...))
            ids.append(cur.lastrowid)
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        raise DuplicateError("cell", str(cell.label_value))
    return ids
```

### Files Modified

| File | Changes |
|------|---------|
| `src/percell3/core/experiment_store.py` | Added `_validate_name()`, called at 4 entry points |
| `src/percell3/core/exceptions.py` | Added `ConditionNotFoundError` class |
| `src/percell3/core/queries.py` | Fixed exception type, added empty-list guards, added rollback |
| `src/percell3/core/__init__.py` | Exported `ConditionNotFoundError` |
| `tests/test_core/test_exceptions.py` | Added `ConditionNotFoundError` tests |
| `tests/test_core/test_queries.py` | Added empty-list, rollback, condition-not-found tests |
| `tests/test_core/test_experiment_store.py` | Added name validation tests |

### Test Coverage

15 new tests added. Total: **183 tests passing, 0 failures**.

Key new tests:
- Path traversal rejection (`../evil`, `DAPI/GFP`, `../../etc`)
- `..` in names rejected
- Empty names rejected
- Valid names pass (`DAPI-488`, `GFP_signal`, `control.1`, `t0`)
- Empty list operations don't crash (`delete_cell_tags([])`, `insert_cells([])`, etc.)
- Rollback verification: after duplicate error, zero cells remain in table
- `ConditionNotFoundError` raised for missing conditions

## Prevention

### Input Validation Patterns

- **Validate at system boundaries**: All public `ExperimentStore` methods validate inputs before passing to helpers or database operations. Since `ExperimentStore` is the only gateway to `.percell` directories, validation at this layer protects everything downstream.
- **Whitelist approach**: The regex `^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$` allows only safe filesystem characters. This is stricter than a blacklist and future-proof.
- **Defense in depth**: Even though creation validates names, names retrieved from the database for read operations were already validated at creation time.

### Exception Hierarchy Discipline

- **One exception per domain concept**: `ChannelNotFoundError`, `ConditionNotFoundError`, `RegionNotFoundError` — never reuse exceptions across entity types.
- **Naming convention**: `<Entity>NotFoundError` for missing entities, `DuplicateError` for uniqueness violations.
- **Document exceptions in docstrings**: Use `Raises:` section in Google-style docstrings.

### Defensive SQL Patterns

- **Guard against empty IN clauses**: Always check `if not items: return` before building `IN (?)` placeholders.
- **Explicit transactions for batch operations**: Use try/commit/except/rollback for any multi-row insert.
- **Prefer `is not None and len() > 0`** over truthiness for Optional list parameters to distinguish "not provided" from "empty list".

### Code Review Checklist

- [ ] String inputs used in filesystem paths are validated with `_validate_name()`
- [ ] Exceptions match the entity being checked
- [ ] All `IN (?)` clauses guarded against empty lists
- [ ] Batch operations wrapped in explicit transactions with rollback
- [ ] New public methods have tests for empty inputs, path traversal, and error paths

## Related

- `todos/001-complete-p1-path-traversal-zarr-names.md`
- `todos/002-complete-p1-wrong-exception-condition.md`
- `todos/003-complete-p1-empty-list-sql-crash.md`
- `todos/004-complete-p1-partial-commit-insert-cells.md`
- `docs/01-core/spec.md` — Core module specification
- `docs/01-core/zarr-layout.md` — Zarr path conventions
- `docs/tracking/decisions-log.md` — ADR-002 (SQLite WAL mode)
