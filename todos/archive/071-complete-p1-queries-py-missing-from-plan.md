---
status: complete
priority: p1
issue_id: "071"
tags: [plan-review, architecture, planning-gap]
dependencies: []
---

# queries.py Completely Missing From Plan

## Problem Statement

The plan lists changes to schema.py, models.py, zarr_io.py, experiment_store.py, and io/models.py — but completely omits queries.py, which is arguably the file with the MOST changes in both Phase 1 and Phase 2.

## Findings

- **Python reviewer**: "queries.py routes ALL SQL through standalone functions. It contains insert_region(), select_regions(), select_region_by_name(), _row_to_region(), and the cells JOIN that aliases region_name. This file is absent from every phase's task list."
- The codebase architecture mandates: all SQL goes through queries.py (standalone functions taking Connection). ExperimentStore delegates to queries.py.

## Proposed Solutions

### A) Add explicit Phase 1.x and Phase 2.x sections for queries.py in the plan

List all functions to rename:
- `insert_region` -> `insert_fov`
- `select_regions` -> `select_fovs`
- `select_region_by_name` -> `select_fov_by_name`
- `_row_to_region` -> `_row_to_fov`
- `count_cells` JOIN update
- `select_cells` JOIN update

In Phase 2: add `insert_bio_rep()`, `select_bio_reps()`, `select_bio_rep_by_name()`, `select_bio_rep_id()`.

- **Pros**: Complete plan.
- **Cons**: None.
- **Effort**: Small (plan update only).
- **Risk**: None.

## Technical Details

Affected file: `src/percell3/core/queries.py` — every SQL function that references the regions table.

## Acceptance Criteria

- [ ] Plan has explicit Phase 1.x section for queries.py renames
- [ ] Plan has explicit Phase 2.x section for new bio rep query functions
- [ ] queries.py is addressed before experiment_store.py in the implementation order

## Work Log

- 2026-02-17 — Identified by Python reviewer during plan review

## Resources

- Plan: docs/plans/2026-02-17-feat-data-model-bio-rep-fov-restructure-plan.md
