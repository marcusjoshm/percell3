---
status: pending
priority: p2
issue_id: "092"
tags: [code-review, performance, core]
dependencies: []
---

# `_resolve_bio_rep` Performs 2 Queries in Auto-Resolve Path

## Problem Statement

When `bio_rep=None` and exactly 1 bio rep exists (the common case), `_resolve_bio_rep` executes two queries: `select_bio_reps()` to list names, then `select_bio_rep_id()` to get the ID by name. This is called on every I/O operation (read/write image, labels, mask). During segmentation of 100 FOVs, this adds ~200 unnecessary queries.

## Findings

- **Found by:** performance-oracle, code-simplicity-reviewer
- **Evidence:** `experiment_store.py:172-181` — auto-resolve path calls `select_bio_reps` then `select_bio_rep_id`

## Proposed Solutions

### Solution A: Single query returning both id and name (Recommended)
- Replace the two-query path with `SELECT id, name FROM bio_reps ORDER BY id` and check length
- **Effort:** Small | **Risk:** Low

## Acceptance Criteria

- [ ] Auto-resolve path uses a single query
- [ ] Behavior unchanged: auto-resolves when 1 bio rep, raises when >1

## Work Log

- 2026-02-17: Identified during code review
