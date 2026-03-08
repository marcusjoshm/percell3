---
title: "Documentation Audit, Cleanup, and Gap-Fill"
type: refactor
status: active
date: 2026-03-08
---

# Documentation Audit, Cleanup, and Gap-Fill

## Summary

Full audit of PerCell 3's documentation corpus (~273 files) against the current codebase state. The project underwent a major architecture change (run-scoped → layer-based) and a rapid decapping sensor workflow sprint (March 3-6) that added 6 plugins, new import mechanisms, and CSV export features. Many todos, brainstorms, and plans are now stale, obsolete, or reference removed code. This plan archives completed work, triages pending todos, fills documentation gaps for undocumented features, and updates CLAUDE.md.

## Scope

- **In scope:** todos/, docs/brainstorms/, docs/plans/, docs/solutions/, CLAUDE.md
- **Focus area:** Decapping sensor workflow and all March 3-6 sprint changes
- **Out of scope:** Code refactoring (menu.py monolith stays as-is), new feature work, test coverage gaps

## Acceptance Criteria

- [ ] All 125 completed todos moved to `todos/archive/`
- [ ] All shipped brainstorms/plans moved to `docs/archive/brainstorms/` and `docs/archive/plans/`
- [ ] Historical/resolved solution docs moved to `docs/archive/solutions/`
- [ ] Every pending todo (45 files) classified as: still-relevant, resolved-by-refactor, or complete
- [ ] Obsolete/resolved pending todos archived with status annotation
- [ ] Retroactive design notes created for nan_zero plugin, NaN-safe metrics, and threshold pair filter
- [ ] Partially-stale solution docs annotated with current status
- [ ] CLAUDE.md updated for current architecture, plugins, workflows, and domain terms
- [ ] Decapping workflow brainstorm/plan verified against final 11-step implementation

---

## Phase 1: Create Archive Structure

- [ ] Create directory `todos/archive/`
- [ ] Create directory `docs/archive/brainstorms/`
- [ ] Create directory `docs/archive/plans/`
- [ ] Create directory `docs/archive/solutions/`

## Phase 2: Archive Completed Todos (Mechanical)

Move all 125 completed todo files (matching `*-complete-*` pattern) from `todos/` to `todos/archive/`.

- [ ] Move all `todos/*-complete-*.md` files to `todos/archive/`
- [ ] Verify count: 125 files moved, 45 pending files remain

## Phase 3: Triage Pending Todos Against Current Codebase

Read each of the 45 pending todos and classify against the current codebase. For each todo, check whether the referenced file, function, and issue still exist.

### 3a: Mark Obsolete Todos as Resolved-by-Refactor

These todos reference `segmentation_runs`, `threshold_runs`, or run-scoped concepts that no longer exist in the layer-based architecture:

- [ ] Todo 123 (missing fov_id on threshold_runs) → `resolved-by-refactor`: `threshold_runs` table removed, replaced by `thresholds` with `source_fov_id`
- [ ] Todo 124 (orphaned segmentation_runs on reseg) → `resolved-by-refactor`: `segmentation_runs` table removed, `segmentations` are global entities with CASCADE
- [ ] Todo 127 (reseg leaves stale zarr masks) → `resolved-by-refactor`: segmentation model changed to global entities
- [ ] Todo 128 (analysis_runs disconnected from outputs) → `resolved-by-refactor`: `analysis_runs` schema redesigned

For each: update the YAML frontmatter to `status: resolved-by-refactor`, add a note explaining the architecture change, then move to `todos/archive/`.

### 3b: Verify and Mark Resolved Todos as Complete

These todos appear resolved in the current codebase but need verification:

- [ ] Todo 122 (layering violation queries imports measure) → verify no cross-layer imports remain, then mark `complete`
- [ ] Todo 132 (duplicated schema in _ensure_tables) → verify `_ensure_tables()` uses single `_SCHEMA_SQL`, then mark `complete`
- [ ] Todo 148 (stat.get("run_id") wrong key) → verify `_segment_cells` no longer references `run_id`, then mark `complete` or `resolved-by-refactor`

For each verified todo: update status, move to `todos/archive/`.

### 3c: Verify Partially-Resolved Todos

These need codebase checks to determine current status:

- [ ] Todo 126 (missing ON DELETE CASCADE FKs) → read current `schema.py`, audit all FK definitions for CASCADE. If all FKs covered, mark `complete`. If gaps remain, update the todo with current gaps only.
- [ ] Todo 133 (hardcoded particle metric names) → grep for hardcoded metric strings outside `core/constants.py`. If clean, mark `complete`. If scattered references remain, update todo with specific locations.
- [ ] Todo 142 (delete_cells_for_fov redundant cascade) → check if `cells.fov_id ON DELETE CASCADE` makes the manual deletion function redundant. Update accordingly.
- [ ] Todo 145 (menu FOV selection duplicated 9x) → recount duplication instances after decapping sprint. Update the count in the todo (likely worse now).
- [ ] Todo 125 (missing composite index measurements) → check current schema for `idx_measurements_cell_channel_scope` or equivalent index.

### 3d: Confirm Remaining 27 Todos Are Still Relevant

Spot-check a sample of the remaining pending todos to confirm they still apply. Focus on P1 items:

- [ ] Todo 119 (transaction safety gap stale particle cleanup) → verify conditional commit pattern in `queries.py`
- [ ] Todo 120 (stale masked measurements on rethreshold) → verify `write_mask()` cleanup logic
- [ ] Todo 121 (bind param overflow add_measurements) → verify IN-clause batching status
- [ ] Todo 138 (insert_cells fragile lastrowid) → verify `queries.insert_cells()` still uses lastrowid pattern
- [ ] Todo 140 (has_masked_measurements any() bug) → verify pandas `.any()` usage
- [ ] Todo 141 (unbounded IN clauses missing batching) → verify batching across query functions

For todos confirmed still relevant: leave in `todos/` with no changes.
For todos found to be resolved: update status, move to `todos/archive/`.

## Phase 4: Archive Shipped Brainstorms and Plans

### 4b: Archive Shipped Brainstorms

Move these 30 shipped brainstorm files to `docs/archive/brainstorms/`:

- [ ] `2026-02-12-io-module-design-brainstorm.md`
- [ ] `2026-02-13-cellpose-segmentation-workflow-brainstorm.md`
- [ ] `2026-02-13-cli-interactive-menu-brainstorm.md`
- [ ] `2026-02-17-cli-ux-improvements-brainstorm.md`
- [ ] `2026-02-17-data-model-bio-rep-fov-restructure-brainstorm.md`
- [ ] `2026-02-18-io-redesign-metadata-assignment-brainstorm.md`
- [ ] `2026-02-19-measurement-cli-brainstorm.md`
- [ ] `2026-02-19-segmentation-fov-selection-ui-brainstorm.md`
- [ ] `2026-02-19-thresholding-module-brainstorm.md`
- [ ] `2026-02-20-data-model-fov-centric-redesign-brainstorm.md`
- [ ] `2026-02-20-menu-ui-redesign-brainstorm.md`
- [ ] `2026-02-23-prism-csv-export-brainstorm.md`
- [ ] `2026-02-24-3d-surface-plot-plugin-brainstorm.md`
- [ ] `2026-02-24-local-background-subtraction-plugin-brainstorm.md`
- [ ] `2026-02-25-missing-percell-processing-steps-brainstorm.md`
- [ ] `2026-02-26-split-halo-condensate-analysis-brainstorm.md`
- [ ] `2026-02-27-copy-segmentation-labels-between-fovs-brainstorm.md`
- [ ] `2026-02-27-napari-background-subtraction-widget-brainstorm.md`
- [ ] `2026-02-27-tiff-export-feature-brainstorm.md`
- [ ] `2026-02-28-run-scoped-architecture-brainstorm.md`
- [ ] `2026-03-02-image-calculator-plugin-brainstorm.md`
- [ ] `2026-03-02-layer-based-architecture-redesign-brainstorm.md`
- [ ] `2026-03-02-tile-scan-stitching-import-brainstorm.md`
- [ ] `2026-03-04-background-subtraction-plugin-brainstorm.md`
- [ ] `2026-03-04-csv-export-fov-filter-brainstorm.md`
- [ ] `2026-03-04-fix-threshold-bg-subtraction-plugin-brainstorm.md`
- [ ] `2026-03-04-import-fovs-from-percell-project-brainstorm.md`
- [ ] `2026-03-05-decapping-sensor-workflow-brainstorm.md`
- [ ] `2026-03-05-imagej-roi-import-plugin-brainstorm.md`
- [ ] `2026-03-05-user-prefix-naming-brainstorm.md`

Keep 4 brainstorms for unimplemented features in place, add `status: deferred` to YAML frontmatter:

- [ ] `2026-02-24-per-condition-channels-brainstorm.md` — schema change, never implemented
- [ ] `2026-02-25-cell-tracking-multi-timepoint-brainstorm.md` — new module, never implemented
- [ ] `2026-02-27-replace-tkinter-with-qt-dialogs-brainstorm.md` — still using tkinter
- [ ] `2026-02-27-named-threshold-runs-and-state-consistency-brainstorm.md` — partially subsumed by layer-based named thresholds

**Note:** Archive the decapping brainstorm *after* Phase 6a verifies/updates it.

### 4c: Archive Shipped Plans

Move these 44 shipped plan files to `docs/archive/plans/`:

- [ ] `2026-02-12-feat-io-module-tiff-import-plan.md`
- [ ] `2026-02-12-refactor-core-module-review-fixes-plan.md`
- [ ] `2026-02-13-feat-cli-interactive-menu-plan.md`
- [ ] `2026-02-13-feat-segmentation-engine-headless-plan.md`
- [ ] `2026-02-13-feat-segmentation-module-cellpose-plan.md`
- [ ] `2026-02-13-refactor-cli-module-review-fixes-plan.md`
- [ ] `2026-02-13-refactor-io-workflow-p2-p3-review-fixes-plan.md`
- [ ] `2026-02-16-feat-next-work-phase-segment-merge-and-measure-plan.md`
- [ ] `2026-02-16-feat-segment-module-3b-napari-viewer-plan.md`
- [ ] `2026-02-17-feat-data-model-bio-rep-fov-restructure-plan.md`
- [ ] `2026-02-17-feat-napari-install-test-and-next-phase-plan.md`
- [ ] `2026-02-17-feat-todo-cleanup-and-cli-ux-improvements-plan.md`
- [ ] `2026-02-18-feat-io-redesign-condition-biorep-hierarchy-plan.md`
- [ ] `2026-02-18-feat-table-first-import-assignment-ui-plan.md`
- [ ] `2026-02-19-feat-measurement-cli-plan.md`
- [ ] `2026-02-19-feat-segmentation-fov-selection-ui-plan.md`
- [ ] `2026-02-19-feat-thresholding-module-plan.md`
- [ ] `2026-02-20-feat-cellpose-napari-segmentation-widget-plan.md`
- [ ] `2026-02-20-feat-percell3-ui-cosmetic-refresh-plan.md`
- [ ] `2026-02-20-fix-csv-export-directory-path-crash-plan.md`
- [ ] `2026-02-20-refactor-fov-centric-flat-data-model-plan.md`
- [ ] `2026-02-23-feat-menu-ui-two-tier-redesign-plan.md`
- [ ] `2026-02-23-feat-particle-analysis-workflow-plan.md`
- [ ] `2026-02-23-feat-prism-csv-export-plan.md`
- [ ] `2026-02-24-feat-3d-surface-plot-plugin-plan.md`
- [ ] `2026-02-24-feat-plugin-manager-and-local-bg-subtraction-plan.md`
- [ ] `2026-02-25-feat-missing-percell-processing-steps-plan.md`
- [ ] `2026-02-26-feat-split-halo-condensate-analysis-plugin-plan.md`
- [ ] `2026-02-27-feat-copy-segmentation-labels-between-fovs-plan.md`
- [ ] `2026-02-27-feat-napari-background-subtraction-widget-plan.md`
- [ ] `2026-02-27-feat-tiff-export-for-fov-images-plan.md`
- [ ] `2026-02-28-refactor-run-scoped-architecture-plan.md`
- [ ] `2026-03-02-feat-image-calculator-plugin-plan.md`
- [ ] `2026-03-02-feat-tile-scan-stitching-import-plan.md`
- [ ] `2026-03-02-refactor-layer-based-architecture-plan.md`
- [ ] `2026-03-03-feat-tiff-export-fov-layers-plan.md`
- [ ] `2026-03-04-feat-background-subtraction-plugin-plan.md`
- [ ] `2026-03-04-feat-csv-export-fov-filter-plan.md`
- [ ] `2026-03-04-feat-import-fovs-from-percell-project-plan.md`
- [ ] `2026-03-04-feat-unassign-segmentation-threshold-from-fov-plan.md`
- [ ] `2026-03-04-fix-threshold-bg-subtraction-plugin-plan.md`
- [ ] `2026-03-05-feat-decapping-sensor-workflow-plan.md`
- [ ] `2026-03-05-feat-imagej-roi-import-plan.md`
- [ ] `2026-03-05-feat-user-prefix-naming-plan.md`

Keep 1 plan for unimplemented feature in place with `status: deferred`:

- [ ] `2026-02-24-feat-per-condition-channel-support-plan.md`

Do NOT archive the current plan (`2026-03-08-refactor-documentation-audit-and-cleanup-plan.md`).

**Note:** Archive the decapping plan *after* Phase 6a verifies/updates it.

### 4d: Archive Historical Solution Documents

Move 3 historical/resolved solution docs to `docs/archive/solutions/`:

- [ ] `run-scoped-architecture-refactor-learnings.md` → add header annotation: "Architecture: run-scoped (historical, superseded by layer-based redesign 2026-03-02)"
- [ ] `napari-viewer-datamodel-merge-api-conflicts.md` → add header annotation: "Historical: merge conflicts resolved, kept for multi-branch strategy reference"
- [ ] `measurement-cli-and-threshold-prerequisites.md` → add header annotation: "Resolved: auto-measurement in layer-based architecture eliminated this gap"

## Phase 5: Annotate Partially-Stale Solution Documents

For solution docs that remain in `docs/solutions/` but have partially-stale content, add a "Current Status" annotation section at the top (below YAML frontmatter):

- [ ] `cli-module-code-review-findings.md` → note which P2 findings were addressed by layer-based refactor, which remain pending
- [ ] `viewer-module-code-review-findings.md` → verify 3 P1 data-loss bugs (dict key mismatch, bare exception, silent label loss) still have fix code via git blame. Add status for each finding.
- [ ] `cli-io-dual-mode-review-fixes.md` → verify fixes applied, add status annotation
- [ ] `cli-io-core-integration-bugs.md` → verify fixes applied, add status annotation
- [ ] `viewer-module-p3-refactoring-and-cleanup.md` → check which cleanups were applied, annotate
- [ ] `import-flow-table-first-ui-and-heuristics.md` → check if table-first import UI was implemented, annotate

## Phase 6: Fill Documentation Gaps — Decapping Sprint Features

### 6a: Verify Decapping Workflow Documentation

- [ ] Read `docs/brainstorms/2026-03-05-decapping-sensor-workflow-brainstorm.md` and verify it matches the final 11-step implementation (originally 10 steps; step 11 added in commit `634ef2f`)
- [ ] Read the decapping plan and verify accuracy
- [ ] If the brainstorm/plan describe 10 steps, update to reflect the final 11-step pipeline including filtered CSV export

### 6b: Create Retroactive Design Note — nan_zero Plugin

Create `docs/solutions/architecture-decisions/nan-zero-plugin-and-nan-safe-metrics.md`:

- [ ] Document motivation: zero-valued pixels in derived FOV channels produce incorrect mean intensity measurements
- [ ] Document the behavioral change: all 7 measurement metrics now use `np.nanmean`, `np.nanmax`, etc. instead of `np.mean`, `np.max`
- [ ] Document the derived FOV four-step contract applied by nan_zero (create FOV, copy fov_config, duplicate cells, auto-measure)
- [ ] Document edge case: cells with all-NaN pixels return NaN measurements (with RuntimeWarning)
- [ ] Reference commit `18c1493`

### 6c: Create Retroactive Design Note — Threshold Pair Filter

Create `docs/solutions/architecture-decisions/threshold-pair-filter-csv-export.md`:

- [ ] Document the filter logic: drop rows where `{channel}_area_mask_inside == 0`, keep only cell_ids with exactly 2 remaining rows (1 per threshold type)
- [ ] Document where it appears: decapping workflow step 11 AND generic `_offer_threshold_dedup_filter()` in CSV export menu
- [ ] Document the use case: decapping experiments need matched P-body + dilute-phase threshold measurements per cell
- [ ] Reference commit `634ef2f`

## Phase 7: Update CLAUDE.md

Update the project's CLAUDE.md to reflect the current architecture:

- [ ] Update module structure listing to include new files: `core/tiff_export.py`, `core/constants.py`, `segment/imagej_roi_reader.py`, `io/percell_import.py`
- [ ] Add a "Plugins" subsection listing all 6 plugins (5 analysis + 1 visualization) with one-line descriptions
- [ ] Add "Decapping Sensor Workflow" to Key Domain Terms or add a Workflows section
- [ ] Update Key Domain Terms to include: Threshold, Particle, Plugin, Derived FOV, FOV Config, Segmentation (global entity)
- [ ] Add note about layer-based architecture (schema 4.0.0) replacing the earlier run-scoped model
- [ ] Mention the NaN-safe metrics behavioral change
- [ ] Add the derived FOV four-step contract as a key architectural pattern

## Phase 8: Archive Standalone Doc

- [ ] Move `docs/background_subtraction_plugin_prompt.md` to `docs/archive/` (this is an early prompt doc, superseded by the actual plugin implementation)

---

## Execution Notes

### Ordering and Dependencies

- Phases 1-2 are mechanical (mkdir + mv) and run first
- **Phase 6a must complete before Phase 4 archives the decapping brainstorm/plan** (verify accuracy before archiving)
- Phases 3, 5, 6 can run in parallel (they touch different files)
- Phase 4 depends on Phase 6a completing (decapping docs verified before archival)
- Phase 7 depends on phases 3-6 completing (CLAUDE.md synthesizes all findings)

### Parallelization Opportunities for `/compound:work`

**Wave 1** (parallel, no dependencies):
- Phase 1+2 (create dirs + archive completed todos) — one subagent
- Phase 3a-3b (obsolete/resolved todos) — one subagent
- Phase 3c-3d (verify partially-resolved and remaining todos) — one subagent
- Phase 5 (annotate stale solutions) — one subagent
- Phase 6 (verify decapping docs + create design notes) — one subagent

**Wave 2** (depends on Wave 1):
- Phase 4 (archive brainstorms/plans) — depends on Phase 6a completing
- Phase 8 (archive standalone doc) — one subagent, can run with Phase 4

**Wave 3** (depends on Waves 1-2):
- Phase 7 (CLAUDE.md update) — depends on all prior phases

### File Counts

| Action | Count |
|--------|-------|
| Archive completed todos | ~125 |
| Archive shipped brainstorms | ~30 |
| Archive shipped plans | ~41 |
| Archive historical solutions | 3 |
| Triage pending todos | 45 |
| Annotate partial solutions | 6 |
| Create new design notes | 2 |
| Update CLAUDE.md | 1 |
| Update deferred brainstorms | 4 |
| Archive standalone doc | 1 |
| **Total files touched** | **~258** |

---

## Sources

- **Research directory:** `.workflows/plan-research/docs-audit-cleanup/agents/`
  - `repo-research.md` — Current codebase inventory, plugin list, menu structure, CSV export architecture
  - `learnings.md` — Solution document audit with relevance ratings and pattern extraction
  - `git-history.md` — Chronological commit analysis of decapping sprint (March 3-6)
  - `specflow.md` — Pending todo triage, brainstorm/plan classification, gap analysis with 11 clarification questions resolved
- **Key codebase references:**
  - `src/percell3/cli/menu.py:4584-5209` — Decapping sensor workflow implementation
  - `src/percell3/core/schema.py` — Current schema (4.0.0, layer-based)
  - `src/percell3/plugins/builtin/` — All 6 plugins
  - `src/percell3/measure/metrics.py` — NaN-safe metrics
