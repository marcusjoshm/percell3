---
status: pending
priority: p2
issue_id: "075"
tags: [plan-review, architecture, data-integrity]
dependencies: []
---

# zarr_path Column is Computed but Stored — Desynchronization Risk

## Problem Statement

The zarr_path column in the regions (fovs) table stores a computed path, but `_resolve_region()` already recomputes it and never reads from the database. Storing it creates desynchronization risk if bio rep names could change.

## Findings

- **Architecture strategist**: "add_region() computes and stores zarr_path, but _resolve_region() recomputes via zarr_io.image_group_path(). The stored value is already redundant. With bio_rep added, if a bio rep were renamed, the stored path would be stale."

## Proposed Solutions

### A) Drop zarr_path column from fovs table

Compute the path in `_resolve_fov()` on demand. Remove the column from the schema.

- **Pros**: No stale data, simpler schema, single source of truth.
- **Cons**: Loses diagnostic value of seeing stored paths in raw DB queries.
- **Effort**: Small.
- **Risk**: Low.

### B) Keep zarr_path as diagnostic-only derived column

Always recompute zarr_path on write (INSERT and UPDATE). Never use it for actual path resolution. Document it as diagnostic-only.

- **Pros**: Retains diagnostic value for manual DB inspection.
- **Cons**: Still requires maintenance on writes, still technically redundant.
- **Effort**: Small.
- **Risk**: Low.

## Technical Details

Affected files:
- `src/percell3/core/queries.py` — INSERT into regions/fovs includes zarr_path
- `src/percell3/core/experiment_store.py` — `_resolve_region()` / `_resolve_fov()` recomputes path
- `src/percell3/core/schema.py` — column definition

Current flow:
1. `add_region()` computes `zarr_path = zarr_io.image_group_path(condition, region)` and stores it
2. `_resolve_region()` computes `zarr_io.image_group_path(condition, region)` independently
3. The stored value is never read for path resolution

## Acceptance Criteria

- [ ] zarr_path is either dropped or documented as diagnostic-only
- [ ] No code path reads zarr_path from DB for actual path resolution
- [ ] If kept, zarr_path is recomputed on every write including bio_rep

## Work Log

- 2026-02-17 — Identified by architecture strategist during plan review

## Resources

- Plan: docs/plans/2026-02-17-feat-data-model-bio-rep-fov-restructure-plan.md
