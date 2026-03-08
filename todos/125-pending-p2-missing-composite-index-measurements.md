---
status: complete
priority: p2
issue_id: "125"
tags: [code-review, schema, performance]
dependencies: []
resolution: "Composite index idx_measurements_cell_channel_scope ON measurements(cell_id, channel_id, scope) now exists in schema.py (line 229-230). Verified 2026-03-08."
---

# Missing composite index on measurements(cell_id, channel_id, scope)

## Problem Statement

The `measurements` table has a UNIQUE constraint on `(cell_id, channel_id, metric, scope)` but no composite index optimized for the common query pattern of `WHERE cell_id IN (...) AND channel_id = ? AND scope = ?`. This forces SQLite to scan the UNIQUE index inefficiently for range queries.

## Findings

- **Found by:** performance-oracle
- Most measurement queries filter by `cell_id` + `channel_id` + optional `scope`
- The UNIQUE index key order is `(cell_id, channel_id, metric, scope)` which works for exact lookups but is suboptimal for range scans on `cell_id IN (...)`
- `select_measurements` builds OR clauses that can defeat index usage
- For large experiments (10k+ cells), this becomes a meaningful bottleneck

## Proposed Solutions

### Solution A: Add covering index (Recommended)

Add `CREATE INDEX idx_measurements_cell_channel_scope ON measurements(cell_id, channel_id, scope)`.

**Pros:** Speeds up common queries, no code changes needed
**Cons:** Slightly more disk space and write overhead
**Effort:** Small
**Risk:** Low

## Acceptance Criteria

- [ ] Index added to schema
- [ ] Common measurement queries verified to use the index
- [ ] No regression in write performance

## Technical Details

- **File:** `src/percell3/core/schema.py` — add index DDL
