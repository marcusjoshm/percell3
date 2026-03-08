---
title: "Layer-Based Architecture Redesign: From Run-Scoped to Global Layers"
category: architecture-decisions
tags: [refactor, schema, segmentation, thresholding, measurement, layer-based, auto-measurement, zarr, sqlite, config-matrix]
module: core, measure, segment, cli, plugins
symptom: "Over-engineered measurement configuration manager with 7 CLI sub-handlers (~365 lines); users found it 'confusing, not intuitive, and doesn't make sense'; auto-measure silently reports success with 0 records; seg_runs ordering inconsistency ([0] vs [-1]); per-FOV scoping prevents sharing segmentations across FOVs"
root_cause: "Configuration abstraction mismatch — measurement_configs/measurement_config_entries tables and config CRUD add indirection layers that don't match how microscopists think about their data; per-FOV run ownership prevents common use case of applying one segmentation to multiple FOVs"
fix: "Replace per-FOV run-scoped model with global layer-based architecture: segmentations and thresholds are independent global entities composed through a per-FOV configuration matrix; measurements become fully automatic side effects of layer creation/modification"
date: 2026-03-02
status: complete
severity: architecture
branch: refactor/run-scoped-architecture
commits: 13
files_changed: 59
insertions: 9463
deletions: 2606
tests_final: 1132
schema_version: "4.0.0"
---

# Layer-Based Architecture Redesign: From Run-Scoped to Global Layers

This document captures the full two-iteration refactor journey: the initial run-scoped architecture (Phases 1-4), its review and rejection, and the layer-based redesign (Phases 1-10) that replaced it. For detailed analysis of the first iteration's problems, see [run-scoped-architecture-refactor-learnings.md](run-scoped-architecture-refactor-learnings.md).

## Problem: What Was Wrong with the First Iteration

The initial run-scoped architecture introduced named segmentation and threshold runs as **per-FOV entities**. Each FOV owned its own runs, and a `measurement_configs` / `measurement_config_entries` system mapped which runs to use for measurement.

Five core problems emerged:

1. **Over-engineered configuration management.** Two new tables plus 7 CLI sub-handlers (~365 lines) for a concept users think of as "pick a seg, pick a threshold, apply to FOVs." The entity chain (FOV -> config_entry -> measurement_config -> seg_run -> threshold_run -> measurements) had too many indirection layers.

2. **Measurements required explicit triggering.** Users had to manually run measurements. Auto-measure was added to the threshold flow but silently reported success even with zero records written.

3. **Per-FOV scoping prevented segmentation sharing.** Users frequently want to apply one segmentation to multiple FOVs with matching dimensions. Per-FOV ownership made this require "copy" operations instead of simple assignment.

4. **Inconsistent run resolution.** `measure_fov()` used `seg_runs[0]` (oldest) while the threshold flow used `seg_runs[-1]` (latest), causing silent measurement failures.

5. **No migration path.** Zarr paths changed from `fov_{id}/0` to `fov_{id}/seg_{run_id}/0` with no migration utility. Old experiments silently produced empty results.

## What Triggered the Redesign

Direct user feedback during review:

> "I don't like the configuration manager. It's very confusing, not intuitive, and for the most part doesn't make sense."

> "There's no reason why some metrics aren't measured and some are. Measurements are cheap."

> "Users need to choose from multiple segmentations, multiple thresholding, and apply to a list of FOVs."

The desired workflow was: pick a segmentation + pick a threshold + pick FOVs = done. No config entities, no active config tracking, no manual measurement step.

## Solution: Layer-Based Architecture

The redesign replaced the per-FOV run-scoped model with a **layer-based architecture** built on a key insight: segmentations, thresholds, and channel images are independent **layers** that exist globally and are composed through configuration.

### Ten Key Architectural Decisions

| # | Decision | Old (Run-Scoped) | New (Layer-Based) |
|---|----------|-------------------|-------------------|
| 1 | Entity ownership | Per-FOV (`fov_id` FK) | Global entities, `source_fov_id` for provenance |
| 2 | Zarr paths | `fov_{id}/seg_{run_id}/0` | `seg_{id}/0` (flat by ID) |
| 3 | Configuration | `measurement_configs` + entries (~560 lines) | `analysis_config` + `fov_config` (one row per FOV-threshold combo) |
| 4 | Measurement trigger | Manual step | Automatic side effect of layer operations |
| 5 | Import behavior | FOV has no segmentation initially | FOV auto-gets `whole_field` segmentation |
| 6 | Particles | Owned by cells (`cell_id` FK) | FOV-level entities (`fov_id + threshold_id`) |
| 7 | Naming | Auto-named, no rename | Auto-named silently, rename via SQLite (zero zarr cost) |
| 8 | Dimension validation | None | Validated on config assignment |
| 9 | Export | No provenance | Config provenance as CSV comment headers |
| 10 | Migration | Implicit (broken) | Fresh start only (schema 4.0.0) |

### What Was Removed (~560 lines)

- `measurement_configs` table (30 lines schema)
- `measurement_config_entries` table
- Config CRUD queries (~120 lines in `queries.py`)
- `auto_create_default_config()` (~45 lines)
- 7 CLI config management sub-handlers (~365 lines in `menu.py`)

### What Replaced It

**Schema** — Two tables replace the four-table config system:

```sql
CREATE TABLE IF NOT EXISTS analysis_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS fov_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config_id INTEGER NOT NULL REFERENCES analysis_config(id) ON DELETE CASCADE,
    fov_id INTEGER NOT NULL REFERENCES fovs(id) ON DELETE CASCADE,
    segmentation_id INTEGER NOT NULL REFERENCES segmentations(id) ON DELETE CASCADE,
    threshold_id INTEGER REFERENCES thresholds(id) ON DELETE SET NULL,
    scopes TEXT NOT NULL DEFAULT '["whole_cell"]'
);
```

One row per FOV-threshold combination. Partial unique indexes handle NULL `threshold_id`.

**Auto-measurement pipeline** (`measure/auto_measure.py`, 356 lines) — Four event-driven functions:

- `on_segmentation_created()` — Extract cells, measure all channels `whole_cell` scope
- `on_threshold_created()` — Extract particles, assign to cells, measure `mask_inside`/`mask_outside`
- `on_labels_edited()` — Detect changes via `np.array_equal`, re-extract and re-measure
- `on_config_changed()` — Detect unmeasured combos, auto-compute missing measurements

Key contract: **auto-measurement failures never roll back layer creation**. The entity persists; failures are logged and retried on next trigger.

**Whole-field segmentation on import** — Every FOV auto-gets a `whole_field` segmentation (all pixels = label 1) at import time. No FOV ever lacks a segmentation. Reuses existing whole-field segs with matching dimensions to avoid duplication.

**CLI matrix view** — 7 thin dispatcher handlers replacing 7 inline-logic handlers: show matrix, assign seg, assign threshold, rename seg, rename threshold, delete seg, delete threshold. Each delegates to `ExperimentStore` methods.

### Scope of Changes

- **59 files** changed, **9,463 insertions**, **2,606 deletions**
- Net lines added by second iteration: **+395** (vs +3,723 for first iteration)
- Schema version: 4.0.0 with 18 tables, 26 indexes
- **1,132 tests passing** (up from 1,076), 0 failures
- All 10 plan phases marked complete

## Patterns & Prevention

Seven recurring patterns across both iterations, with prevention rules:

| Pattern | Example | Prevention |
|---------|---------|------------|
| **Silent failures** | Auto-measure printed "complete" with 0 records | Return counts from write functions; callers must check; log *why* zero occurred |
| **Dict key mismatches** | `channel_name` vs `channel`; `run_id` vs `segmentation_id` | Typed dataclasses at API boundaries, never raw dicts |
| **Dual-store desync** | Stale particles, missing zarr migration | "Write-Invalidate-Cleanup" pattern; ExperimentStore as single mutation authority |
| **Implicit ordering** | `seg_runs[0]` vs `seg_runs[-1]` | Pass explicit IDs as parameters; never index lists to select domain entities |
| **Encapsulation leaks** | `store._conn` access outside core | Hexagonal boundary enforcement as quality gate |
| **Over-engineering** | Config entity system (~560 lines) rejected | Write CLI interaction script before schema; "explain to a scientist" test |
| **Missing batching** | Unbounded `IN` clauses hit SQLite 999-param limit | `DEFAULT_BATCH_SIZE` in `constants.py`; not all callsites converted (todos 121, 141) |

### Over-Engineering Warning Signs

1. Entity count exceeds user concept count (two tables for one action)
2. CRUD operations outnumber domain verbs (seven handlers for "assign")
3. Indirection depth > 2 (3+ joins to answer "what segmentation is active?")
4. Auto-creation exists to bypass your own UI

### Code Removal Signs

1. The user cannot explain what it does in one sentence
2. Auto-creation exists to bypass the feature
3. Handler-to-action ratio exceeds 2:1
4. The replacement is shorter AND more capable

### Iterative Refactoring Rules

1. Each commit passes the full test suite independently
2. First commit delivers one end-to-end user-visible change
3. Measure net lines, not gross lines (+395 vs +3,723 for more functionality)
4. Build the parts most likely to be discarded last

### Key Takeaways

- **Design for the user's mental model.** Scientists think in layers and images, not config entities.
- **Make the implicit explicit.** Pass IDs, check return values, version schemas.
- **Validate the abstraction before building.** A 30-minute CLI mockup saves weeks of throwaway code.

## Todos Absorbed by This Refactor

13 pending todos were absorbed: 119-127, 129-130, 132-133. See [run-scoped-architecture-refactor-learnings.md](run-scoped-architecture-refactor-learnings.md) for the original todo list.

14 new todos (138-151) were discovered during code review of the refactored code — 6 at P1, 6 at P2, 2 at P3. Notable: insert_cells fragile lastrowid (138), on_labels_edited rebuilds everything (139), unbounded IN clauses still not fully batched (141).

## Related Documents

### Architecture Chain
```
2026-02-27  Named Threshold Runs brainstorm
    ↓ (superseded)
2026-02-28  Run-Scoped Architecture brainstorm → plan (Phases 1-4 implemented)
    ↓ (reviewed, partially rejected)
2026-03-01  Run-Scoped Learnings doc (this refactor's predecessor)
    ↓ (informed redesign)
2026-03-02  Layer-Based Architecture brainstorm → plan (all 10 phases complete)
    ↓ (documented)
2026-03-02  This document (full journey learnings)
```

### Cross-References
- [run-scoped-architecture-refactor-learnings.md](run-scoped-architecture-refactor-learnings.md) — Phase 1-4 post-mortem
- [segment-module-private-api-encapsulation-fix.md](segment-module-private-api-encapsulation-fix.md) — Hexagonal boundary enforcement
- [viewer-module-code-review-findings.md](viewer-module-code-review-findings.md) — Dict key mismatch anti-pattern
- [cli-module-code-review-findings.md](cli-module-code-review-findings.md) — Menu-as-thin-dispatcher pattern
- `docs/solutions/database-issues/zarr-sqlite-state-mismatch-re-thresholding.md` — Write-Invalidate-Cleanup pattern
- `docs/solutions/design-gaps/measurement-cli-and-threshold-prerequisites.md` — Metric name mismatch (superseded by auto-measurement)
