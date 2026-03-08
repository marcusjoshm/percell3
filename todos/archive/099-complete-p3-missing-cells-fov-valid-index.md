---
status: complete
priority: p3
issue_id: "099"
tags: [code-review, performance, core, schema]
dependencies: []
---

# Missing Composite Index `idx_cells_fov_valid`

## Problem Statement

The most common `select_cells` query filters by `fov_id` and `is_valid`. A composite index `cells(fov_id, is_valid)` would let SQLite satisfy both predicates from a single index scan. Currently requires two separate index lookups.

## Findings

- **Found by:** performance-oracle
- **Evidence:** `schema.py` — only `idx_cells_fov ON cells(fov_id)` exists

## Proposed Solutions

### Solution A: Add composite index
- `CREATE INDEX IF NOT EXISTS idx_cells_fov_valid ON cells(fov_id, is_valid);`
- **Effort:** Small | **Risk:** Low

## Work Log

- 2026-02-17: Identified during code review
