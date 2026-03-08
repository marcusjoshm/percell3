---
status: complete
priority: p3
issue_id: "097"
tags: [code-review, simplicity, core, queries]
dependencies: []
---

# `select_bio_rep_by_name` and `select_bio_rep_id` Are Near-Duplicates

## Problem Statement

Two nearly identical query functions differ only in return type: `select_bio_rep_by_name` returns `sqlite3.Row`, `select_bio_rep_id` returns `int`. Both execute the same query pattern. ~8 LOC of redundancy.

## Findings

- **Found by:** code-simplicity-reviewer, kieran-python-reviewer
- **Evidence:** `queries.py:201-218`

## Proposed Solutions

### Solution A: Merge into one function
- Keep `select_bio_rep_by_name` returning the Row, callers extract `row["id"]` as needed
- **Effort:** Small | **Risk:** Low

## Work Log

- 2026-02-17: Identified during code review
- 2026-02-18: Merged. Removed `select_bio_rep_id()` from queries.py. Updated 3 callers in experiment_store.py to use `select_bio_rep_by_name(conn, name)["id"]`. Tests updated.
