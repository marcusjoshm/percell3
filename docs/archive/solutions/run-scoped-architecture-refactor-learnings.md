---
title: "Run-Scoped Architecture Refactor: Learnings and Current State"
category: architecture-decisions
tags: [refactor, schema, segmentation-runs, threshold-runs, measurement-config, zarr, sqlite, run-scoped]
module: core, measure, cli, segment/viewer, plugins
symptom: "Configuration manager is confusing and unintuitive; auto-measure silently fails; seg_runs ordering inconsistency"
root_cause: "Over-engineered measurement configuration; inconsistent seg_run resolution; missing data migration path"
date: 2026-03-01
status: documenting-before-redesign
severity: architecture
---

> **Architecture: run-scoped (historical, superseded by layer-based redesign 2026-03-02)**

# Run-Scoped Architecture Refactor: Learnings and Current State

This document captures the full state of the run-scoped architecture refactor (Phases 1-4) before the planned redesign. It serves as institutional knowledge for the second iteration.

## What Was Built (Phases 1-4)

### Phase 1: Schema Changes
- Added `segmentation_runs` table with per-FOV named runs and UNIQUE constraint on `(fov_id, name)`
- Added `threshold_runs` table with similar structure
- Added `segmentation_id` FK on `cells` table
- Added `scope` CHECK constraint and `threshold_run_id` FK on `measurements` table
- Added `measurement_configs` and `measurement_config_entries` tables
- Zarr paths migrated from `fov_{id}/0` to `fov_{id}/seg_{run_id}/0`
- Partial unique indexes for nullable UNIQUE constraints (replacing COALESCE sentinels)

### Phase 2: Engine and CLI Updates
- `Measurer` updated with `measure_fov_masked()` for scope-based measurement (mask_inside/mask_outside)
- `CellGrouper` updated for scope-aware grouping
- CLI menu extended with 7 config management sub-handlers (~365 lines)
- Auto-measure integrated into threshold flow
- `DeleteImpact` dataclass for previewing cascade effects before deletion

### Phase 3: Viewer Integration
- Napari viewer updated to read/write labels at run-scoped zarr paths
- Copy Labels Widget: copy segmentation labels across FOVs
- Copy Mask Widget: copy threshold masks across FOVs with particle extraction
- Background Subtraction Widget: flat BG subtraction creating derived FOVs
- Edge Removal Widget: edge-cell removal + minimum area filter with Preview/Apply

### Phase 4: Configuration Manager
- `auto_create_default_config()` — auto-generates config from latest seg/threshold runs
- `MeasurementConfigEntry` mapping FOV -> seg_run -> threshold_run
- Active config tracking with `set_active_measurement_config()`
- Cross-FOV validation (threshold run must belong to same FOV as config entry)
- Config CRUD operations in CLI with 7 sub-menu handlers

## What Works

### Passing Tests
- 29 new tests across the 4 phases (all passing)
- 7 auto-measure -> grouper reproduction tests (all passing)
- 43 tests for recent viewer widgets and plugins (all passing)
- Total: 1076+ tests passing

### Functional Features
- Named segmentation runs with UNIQUE constraint per FOV
- Named threshold runs with similar uniqueness
- Run-scoped zarr label paths (`fov_{id}/seg_{run_id}/0`)
- Cascade delete with impact preview (cells, measurements, particles, config entries)
- Scope-based measurements (mask_inside, mask_outside, whole_cell)
- Plugin input requirements framework (InputKind enum + PluginInputRequirement)
- Cross-FOV label and mask copying
- Derived FOV creation for background subtraction

## Known Bugs

### Bug 1: seg_runs Ordering Inconsistency
- `measure_fov()` used `seg_runs[0]` (oldest) while threshold flow uses `seg_runs[-1]` (latest)
- **Partially fixed**: `measure_fov()` and `measure_cells()` changed to `seg_runs[-1]`
- **Still unfixed**: `measure_fov_masked()` at ~line 200 still uses `seg_runs[0].id`

### Bug 2: Auto-Measure Silent Failure
- `menu.py` line ~2381: auto-measure ignores `measure_fov()` return value
- Always prints "Auto-measurement complete." even if 0 measurements written
- User sees success message but grouper fails downstream

### Bug 3: No Zarr Path Migration
- Old experiments have labels at `fov_{id}/0` (pre-refactor path)
- New code reads from `fov_{id}/seg_{run_id}/0`
- No migration utility exists to move labels from old to new paths
- Old experiments silently produce empty results

## Design Issues (User Feedback)

The user explicitly rejected several design decisions:

### Issue 1: Configuration Manager is Over-Engineered
> "I don't like the configuration manager. It's very confusing, not intuitive, and for the most part doesn't make sense."

The `measurement_config_entries` table and 7 CLI sub-handlers add ~365 lines of code for a concept that most users find confusing. The mapping of FOV -> seg_run -> threshold_run -> config is too many indirection layers.

### Issue 2: Measurements Should Be Automatic
> "There's no reason why some metrics aren't measured and some are. Measurements are cheap."

Current design requires explicit measurement configuration. User wants:
- Whole-cell measurements: automatic after segmentation (cellpose or napari edit)
- Particle measurements: automatic after thresholding
- No manual "run measurements" step

### Issue 3: Run Selection Should Be Simpler
> "Users need to choose from multiple segmentations, multiple thresholding, and apply to a list of FOVs."

Current config manager tries to be too flexible. What's actually needed:
- Pick a segmentation run (from list of named runs)
- Pick a threshold run (from list of named runs)
- Apply to selected FOVs
- That's it. No config entities, no active config tracking.

### Issue 4: Missing Run Naming UX
> "The user should have to name segmentation and measurement runs."

Current auto-naming (e.g., "cyto3_run_1") is not user-friendly. Users need to provide meaningful names at creation time.

### Issue 5: Measurement Reporting is Opaque
User wants a detailed report of what was measured using which segmentation and which threshold. Current system doesn't provide this visibility.

## Complexity Inventory

### Code Added (Phases 1-4)
| Component | Lines | Complexity | Keep? |
|-----------|-------|------------|-------|
| Schema changes (segmentation_runs, threshold_runs) | ~60 | Low | Yes |
| cells.segmentation_id FK | ~10 | Low | Yes |
| measurements.scope + threshold_run_id | ~15 | Low | Yes |
| measurement_configs tables | ~30 | Medium | **Remove** |
| Config CRUD queries | ~120 | Medium | **Remove** |
| Config CLI handlers (7 sub-menus) | ~365 | High | **Remove** |
| auto_create_default_config() | ~45 | Medium | **Remove** |
| measure_fov_masked() | ~80 | Medium | Keep (simplify) |
| DeleteImpact + cascade delete | ~60 | Medium | Keep |
| Plugin input requirements | ~30 | Low | Keep |
| Run-scoped zarr paths | ~20 | Low | Keep |

**Estimated removable code**: ~560 lines (config system)
**Estimated keepable code**: ~275 lines (runs, scopes, cascade, plugins)

## What Went Right (Keep)

1. **Named runs with UNIQUE constraints**: Users need to identify and manage multiple seg/threshold runs. The DB schema is sound.
2. **Run-scoped zarr paths**: Storing labels under `seg_{run_id}` prevents data collisions when multiple runs exist for the same FOV.
3. **Cascade delete with impact preview**: Showing users what will be affected before deletion prevents data loss.
4. **Scope-based measurements**: The mask_inside/mask_outside/whole_cell distinction is essential for the condensate analysis workflow.
5. **Plugin input requirements**: Declaring what a plugin needs (InputKind.SEGMENTATION, InputKind.THRESHOLD) enables validation before execution.

## What Went Wrong (Change)

1. **Configuration manager abstraction**: Added an entire config entity system when users just need to pick runs and apply to FOVs. Over-abstracted.
2. **Manual measurement triggering**: Measurements should be a side-effect of segmentation and thresholding, not a separate manual step.
3. **seg_runs ordering inconsistency**: Different code paths used `[0]` vs `[-1]`, causing silent measurement failures.
4. **No migration path**: Changed zarr paths without providing a migration utility for existing experiments.
5. **Silent failures**: Auto-measure reports success regardless of actual outcome.

## Prevention Strategies

### For the Redesign
1. **Test with real experiments**: Don't just test with fresh data. Import an existing experiment and verify the full flow.
2. **Fail loudly**: If measurements produce 0 records, that's an error, not a no-op. Log warnings and surface to user.
3. **Migration-first**: If changing storage paths, write the migration utility BEFORE changing the read paths.
4. **User-test the UX**: Before building a complex config system, mock up the CLI flow and validate it makes sense to a scientist.
5. **Consistent resolution**: Document and enforce a single strategy for "which run to use when none specified" (latest, not oldest).

### Design Principles for Redesign
1. **Automatic over configurable**: Measurements happen as a side-effect, not as a configured step.
2. **Runs are the unit of organization**: Users think in terms of "which segmentation" and "which threshold", not in terms of config entries.
3. **Reports over configs**: Instead of configuring what to measure, measure everything and let users query/filter results.
4. **Name at creation**: Force users to name runs when creating them, so the names are meaningful.
5. **Simple selection**: Pick a seg run + pick a threshold run + pick FOVs = done. No additional abstraction layer.
6. **Detailed provenance**: Every measurement should record which seg_run and threshold_run produced it, enabling full audit trails.
7. **Flexible mask/label management**: Users should be able to add, delete, rename, and combine masks and labels freely among any image in a zarr file.

## Related Documents

### Plans and Brainstorms
- `docs/plans/2026-02-26-feat-split-halo-condensate-analysis-plugin-plan.md` — Plugin plan (implemented)
- `docs/plans/2026-02-24-feat-plugin-manager-and-local-bg-subtraction-plan.md` — Plugin manager (implemented)
- `docs/brainstorms/2026-02-27-named-threshold-runs-brainstorm.md` — Named threshold runs (brainstorm only, no plan)
- `docs/plans/2026-02-24-feat-per-condition-channel-support-plan.md` — Per-condition channels (planned, not built)

### Existing Solution Documents
- `docs/solutions/database-issues/zarr-sqlite-state-mismatch-re-thresholding.md` — Stale particles after re-thresholding
- `docs/solutions/integration-issues/napari-viewer-datamodel-merge-api-conflicts.md` — Viewer API after bio_rep/FOV refactoring
- `docs/solutions/security-issues/core-module-p1-security-correctness-fixes.md` — Input validation and path traversal prevention
- `docs/solutions/logic-errors/segment-minimum-area-artifact-filtering.md` — Label filtering patterns

### Pending Todos Absorbed by This Refactor
- #106 (complete): Rename "Apply Threshold" to "Grouped Intensity Thresholding"
- #114 (complete): Simplify remove_edge_cells boolean
- #107 (pending): Auto-measure before grouping if no measurements — partially addressed by auto-measure in threshold flow
- #116 (pending): Threshold viewer not showing gaussian blur
- #109 (pending): filter_edge_cells mutation and performance

## Summary

The run-scoped architecture refactor delivered solid infrastructure (named runs, scoped measurements, cascade deletes, plugin requirements) but over-engineered the measurement configuration layer. The ~560 lines of config management code should be removed in favor of automatic measurements triggered by segmentation and thresholding, with simple run selection replacing the config entity system. The remaining ~275 lines of run and scope infrastructure should be preserved and simplified.

**Next step**: Use `/brainstorm` to design the simplified architecture, then implement a second round of refactoring.
