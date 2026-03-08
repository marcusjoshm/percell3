---
status: complete
priority: p3
issue_id: "132"
tags: [code-review, architecture, code-quality]
dependencies: []
---

> **Resolved.** Verified 2026-03-08: `_ensure_tables()` now delegates entirely to `conn.executescript(_SCHEMA_SQL)` with no duplicate DDL. Single source of truth.

# Duplicated schema DDL in _ensure_tables

## Problem Statement

`_ensure_tables()` in `schema.py` duplicates some DDL from `_SCHEMA_SQL`, creating a maintenance risk where schema changes need to be applied in two places.

## Findings

- **Found by:** kieran-python-reviewer
- `_SCHEMA_SQL` contains the canonical schema definitions
- `_ensure_tables()` has additional `CREATE TABLE IF NOT EXISTS` statements that overlap
- Changes to one location may not be reflected in the other

## Proposed Solutions

### Solution A: Use only _SCHEMA_SQL (Recommended)

Remove duplicate DDL from `_ensure_tables()` and have it only execute `_SCHEMA_SQL`.

**Pros:** Single source of truth
**Cons:** Need to verify all tables are covered
**Effort:** Small
**Risk:** Low

## Acceptance Criteria

- [ ] No duplicated DDL
- [ ] All tables created from single source

## Technical Details

- **File:** `src/percell3/core/schema.py`
