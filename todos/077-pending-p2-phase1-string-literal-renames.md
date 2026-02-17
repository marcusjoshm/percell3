---
status: pending
priority: p2
issue_id: "077"
tags: [plan-review, quality, planning-gap]
dependencies: []
---

# Phase 1 "Find-and-Replace" Misses SQL String Literals and Dict Keys

## Problem Statement

The plan describes Phase 1 as "purely mechanical find-and-replace" but this misses SQL string literals, dict key strings, and output messages that contain "region".

## Findings

- **Python reviewer**: "'region' appears in SQL strings like `JOIN regions r`, `r.region_id`, `region_name` as dict keys. A find-and-replace on Python identifiers will not catch SQL string literals."
- `queries.py` line 384 aliases `r.name AS region_name`. Downstream code uses `"region_name"` as a dict key.
- CLI output strings like "Regions processed" need updating too.

## Proposed Solutions

### A) Add explicit string literal grep to Phase 1.8 verification

Add verification steps to Phase 1.8 that grep for string literals containing "region":

```bash
grep -rn '".*region.*"' src/percell3/   # double-quoted strings
grep -rn "'.*region.*'" src/percell3/   # single-quoted strings
```

Review each match and update as appropriate.

- **Pros**: Catches all string-embedded references, comprehensive.
- **Cons**: Some false positives (e.g., "segmentation region" in docstrings may be correct).
- **Effort**: Small.
- **Risk**: None.

### B) Use AST-level refactoring tool

Use a Python AST parser to find all string literals containing "region" and flag them.

- **Pros**: More precise than grep.
- **Cons**: Overkill for this scope, doesn't help with SQL strings anyway.
- **Effort**: Medium.
- **Risk**: Low.

## Technical Details

Known locations requiring string literal updates:

1. **SQL aliases**: `r.name AS region_name` -> `f.name AS fov_name` in queries.py
2. **Dict keys**: `row["region_name"]` -> `row["fov_name"]` in experiment_store.py, CLI commands
3. **CLI output**: `"Regions processed"` -> `"FOVs processed"` in CLI modules
4. **Error messages**: `"Region not found"` -> `"FOV not found"` in exception messages
5. **SQL table name**: `CREATE TABLE regions` -> `CREATE TABLE fovs` in schema.py

## Acceptance Criteria

- [ ] Phase 1.8 includes string literal grep verification
- [ ] SQL string aliases updated (`region_name` -> `fov_name`)
- [ ] Dict key references updated in downstream code
- [ ] CLI output messages updated
- [ ] Error messages updated

## Work Log

- 2026-02-17 — Identified by Python reviewer during plan review

## Resources

- Plan: docs/plans/2026-02-17-feat-data-model-bio-rep-fov-restructure-plan.md
