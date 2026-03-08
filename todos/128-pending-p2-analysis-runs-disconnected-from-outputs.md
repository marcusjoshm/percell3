---
status: resolved-by-refactor
priority: p2
issue_id: "128"
tags: [code-review, schema, architecture]
dependencies: []
---

> **Resolved by layer-based architecture redesign (2026-03-02).** The `analysis_runs` schema was redesigned in the layer-based architecture. The referenced table structure no longer exists in the codebase.

# analysis_runs table disconnected from its outputs

## Problem Statement

The `analysis_runs` table records when analysis was performed but has no FK relationship to the measurements or plugin outputs it produced. There is no way to determine which measurements came from which analysis run, making it impossible to clean up outputs when re-running analysis.

## Findings

- **Found by:** architecture-strategist
- `analysis_runs` has: `id, channel_id, plugin_name, parameters, created_at`
- `measurements` table has no `analysis_run_id` column
- Plugin CSV exports are saved to filesystem with no DB tracking
- When analysis is re-run, old measurements are overwritten via INSERT OR REPLACE but only for matching `(cell_id, channel_id, metric, scope)` tuples
- If a plugin changes its metric names between versions, old metrics persist as orphans

## Proposed Solutions

### Solution A: Add analysis_run_id to measurements (Recommended for future)

Add `analysis_run_id` FK to measurements table so outputs can be traced and cleaned up per-run.

**Pros:** Full traceability, clean re-run semantics
**Cons:** Schema migration, all measurement writers must be updated
**Effort:** Large
**Risk:** Medium

### Solution B: Delete measurements by plugin+channel before re-run

When a plugin runs, delete all measurements for that channel+scope combination first.

**Pros:** Simple, no schema change
**Cons:** Requires knowing which metrics a plugin produces
**Effort:** Small
**Risk:** Low

## Acceptance Criteria

- [ ] Re-running a plugin doesn't leave orphaned metrics
- [ ] Measurement provenance is traceable

## Technical Details

- **File:** `src/percell3/core/schema.py` — `analysis_runs`, `measurements`
- **File:** `src/percell3/plugins/` — plugin base class
