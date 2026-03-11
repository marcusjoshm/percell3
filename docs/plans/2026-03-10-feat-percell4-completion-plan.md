---
title: "PerCell4 Completion — Full P-body Architecture"
type: feat
status: completed
date: 2026-03-10
origin: docs/brainstorms/2026-03-10-percell4-completion-brainstorm.md
---

# PerCell4 Completion Plan

Make percell4 a functional replacement for percell3: full P-body schema, reorganized menu, plugin rewrites with lineage, and workflow execution.

**Origin brainstorm decisions carried forward:**
- Full P-body schema (6.0.0), not incremental columns
- Clean break from percell3 — no migration path
- Status is informational, not gating
- Plugin scalar results stored as measurements
- Workflow params in SQLite DB (workflow_configs table deferred to Step 6)
- Single derived FOV per parent for threshold_bg_subtraction
- lineage_path as cached query column + parent_fov_id as FK source of truth
- Skip plugin parameter ABC change — use per-plugin custom menu handlers instead

---

## Step 1: NaN Spike

**Gate target: validates threshold_bg_subtraction redesign feasibility**

Spike to verify NaN pixel behavior through the full pipeline before committing to the single-derived-FOV approach.

- [x] Create a test image (512x512) with known values inside ROIs and NaN outside
- [x] Verify `np.nanmean`, `np.nanmax`, `np.nanmin`, `np.nanstd`, `np.nanmedian` produce correct results
- [x] Verify `np.nansum` for integrated intensity
- [x] Verify area calculation excludes NaN pixels
- [x] Test edge case: ROI where all pixels are NaN (should produce NaN measurement, not crash)
- [x] Test edge case: ROI at image border partially outside image bounds
- [x] Verify Zarr read/write preserves NaN values (float32/float64)
- [x] Verify napari renders NaN as transparent (not black or zero)
- [x] Verify CSV export handles NaN values correctly
- [x] Verify `scipy.ndimage.label` and `skimage.measure.regionprops` handle NaN input — **NOTE: `scipy.ndimage.label` treats NaN as foreground (non-zero); must replace NaN with 0 before labeling**
- [x] Verify `area` metric excludes NaN pixels (use `mask & ~np.isnan(image)` for derived FOVs)
- [x] Verify NaN round-trip in SQLite REAL columns (may need to store NaN as NULL)
- [x] Add performance benchmarks: `np.nanmean` on 0%/50%/95% NaN images, Zarr compression impact
- [x] Write a summary document with results: `.workflows/nan-spike-results.md`

**Decision point:** If NaN handling fails in any critical path, revisit the threshold_bg_subtraction design before proceeding.

**Fallback design (if NaN spike fails):** Revert to percell3's multi-derived-FOV approach (one per intensity group) which avoids NaN pixels entirely. This would use `parent_fov_id` lineage without NaN-outside-ROI semantics. Document the fallback in the spike results.

### Review Findings (Run 1)

**Critical:**
- `scipy.ndimage.label` treats NaN as foreground (non-zero), which will silently connect disconnected regions through NaN "bridges." Must replace NaN with 0 or use boolean mask before labeling. [best-practices-researcher]
- `np.nanmax` and `np.nanmin` raise `ValueError` (not return NaN) when all pixels are NaN. Wrap in try/except. [best-practices-researcher]
- `area` metric uses `np.sum(mask)` which counts all mask-true pixels including NaN regions. Must change to `mask & ~np.isnan(image)` for derived FOVs. [performance-oracle]
- SQLite `REAL` column may not round-trip IEEE NaN — could convert to NULL. Add explicit NaN round-trip test to spike. [data-integrity-guardian, performance-oracle]

**Serious:**
- Zarr float32 `fill_value` defaults to 0.0, not NaN. Derived FOVs must explicitly set `fill_value=float('nan')` and `dtype=np.float32`. [best-practices-researcher]
- `skimage.regionprops` `intensity_mean` uses `np.mean` (not nanmean) — propagates NaN. Use custom `extra_properties` or PerCell4's own measurement code. [best-practices-researcher]
- If NaN cannot be stored in SQLite REAL, change `value REAL NOT NULL` to `value REAL` (nullable) and store NaN as NULL. [performance-oracle]

**Recommendations:**
- Add timing benchmarks to spike: `np.nanmean` on 0%/50%/95% NaN images, full `measure_fov()` comparison, Zarr round-trip with/without NaN. [performance-oracle]
- Store images as float32 but compute measurements in float64 to avoid rounding errors and overflow. [data-integrity-guardian]
- Verify compression impact of NaN vs zero in Zarr chunks empirically. [performance-oracle]

---

## Step 2: Schema 6.0.0 Migration

**Gate target: P-body schema foundation for all subsequent work**

Migrate from schema 5.1.0 to 6.0.0. **IMPORTANT: `rois`, `cell_identities`, `fov_status_log`, and `pipeline_runs` tables already exist in 5.1.0.** The actual migration delta is adding columns to `fovs` + indexes + FK cascade rules. Estimated test breakage: ~5-10% (not 30-50%).

### 2a. Schema DDL Changes (Delta from 5.1.0)

Reference: `docs/plans/percell_pbody_architecture.md`

**Already exists in 5.1.0 (no action needed):** `rois`, `cell_identities`, `fov_status_log`, `pipeline_runs`, `roi_type_definitions`, `segmentation_sets`, `fov_segmentation_assignments`, `fov_mask_assignments`, `threshold_masks`, `timepoints`

**New columns on `fovs` table:**
- [x] Add `lineage_depth INTEGER DEFAULT 0` to `fovs`
- [x] Add `lineage_path TEXT` to `fovs` (format: `/hex(root_id)/hex(parent_id)/hex(this_id)`)
- [x] Add `display_name TEXT` to `fovs`
- [x] Add `channel_metadata TEXT` (JSON) to `fovs`
- [x] Add `pipeline_run_id` to `fovs` (if not already present)

**New indexes:**
- [x] `CREATE INDEX idx_fovs_lineage_path ON fovs(lineage_path) WHERE lineage_path IS NOT NULL`

**FK cascade rules (add to all existing FKs):**
- [x] Add ON DELETE CASCADE/RESTRICT rules to all foreign keys
- [x] `cell_identities.origin_fov_id` → ON DELETE RESTRICT (prevents breaking identity anchor)
- [x] `rois.fov_id` → ON DELETE CASCADE
- [x] `measurements.roi_id` → ON DELETE CASCADE
- [x] `fov_status_log.fov_id` → ON DELETE CASCADE

**Backfill existing data:**
- [x] Backfill `lineage_path` for existing FOVs (root FOVs get `/hex(id)`, derived FOVs built iteratively from parent paths)
- [x] Backfill `lineage_depth` from parent chain

**Reconciliation needed:**
- [x] Reconcile `cell_identities` columns between P-body spec (`experiment_id`, `origin_label_id`) and 5.1.0 (`roi_type_id`)
- [x] Ensure all new DDL uses BLOB(16) for UUIDs (NOT TEXT from P-body spec)

**Deferred to Step 6:** `workflow_configs` table creation (YAGNI — not consumed until Step 6)

**NaN storage fix:**
- [x] Recreate `measurements` table to change `value REAL NOT NULL` to `value REAL` (nullable) — SQLite does not support ALTER COLUMN. Store NaN as NULL. (Required if Step 1 spike confirms NaN cannot round-trip in SQLite REAL.)

**Migration bookkeeping:**
- [x] Update `SCHEMA_VERSION` to `"6.0.0"`
- [x] Add migration path `"5.1.0->6.0.0"` in `migration.py`
- [x] Wrap migration in explicit transaction with `PRAGMA foreign_key_check` post-migration
- [x] Add backup/rollback path: copy DB file before migration, restore on failure
- [x] Fix `MERGE_TABLE_ORDER`: move `pipeline_runs` before tables that reference it
- [x] Add `PRAGMA trusted_schema=OFF` to connection configuration

### 2b. Models Update

- [x] **First: Verify FovInfo actually works against real DB queries** — `FovInfo.display_name: str` has no default but DB has no `display_name` column. FovInfo may never have been functionally tested. Fix model-schema alignment before adding new fields.
- [x] Add `lineage_depth`, `lineage_path`, `display_name`, `channel_metadata` to `FovInfo` dataclass (note: `parent_fov_id`, `derivation_op`, `derivation_params` may already exist — verify)
- [x] Verify `CellIdentity` and `RoiInfo` dataclasses already exist with correct fields
- [x] Use `frozen=True, slots=True, kw_only=True` for any new dataclasses
- [x] Add new exception subclasses: `RoiNotFoundError`, `LineageError`

### 2c. ExperimentDB CRUD Updates

- [x] Update `insert_fov()` to accept new lineage fields (`lineage_depth`, `lineage_path`, `display_name`, `channel_metadata`)
- [x] Update `create_derived_fov()` to set `lineage_depth`, `lineage_path`, `display_name`, `channel_metadata` (method already exists — only missing these fields)
- [x] Fix `create_derived_fov()` to copy `pixel_size_um` from source FOV (currently omitted — silently corrupts physical measurements)
- [x] Wrap derived FOV 4-step contract in single `db.transaction()` for atomicity
- [x] Implement or verify measurement dispatch for derived FOVs — documented as stub; plugins must manually call `measure_fov()` after creating derived FOVs
- [x] Add `get_fov_lineage()` method using `lineage_path LIKE` queries
- [x] Add bulk `insert_rois()` using `executemany()` for derived FOV ROI duplication
- [x] Verify existing ROI/cell_identity/measurement CRUD methods work with new columns
- [x] Add `log_fov_status()` with `pipeline_run_id` parameter (if not already present)
- [x] Update merge logic: fix `MERGE_TABLE_ORDER` for `pipeline_runs` position

### 2d. ExperimentStore Updates

- [x] Add `derive_fov()` public method orchestrating DB + LayerStore
- [x] Update `insert_roi_checked()` (renamed from cell operations)
- [x] Add `get_fov_tree()` for lineage tree queries
- [x] Add cross-lineage measurement query: join `measurements` through `rois.cell_identity_id` across derived FOVs (core P-body use case)
- [x] Scope viewer module updates: 37 `store.db.*` calls identified across 6 viewer files — none require functional changes for schema 6.0.0

### 2e. Test Migration

- [ ] Update test fixtures for new FovInfo fields (lineage_depth, lineage_path, display_name, channel_metadata)
- [ ] Add tests for lineage: derived FOV creation, lineage_path queries, lineage_depth computation
- [ ] Add tests for FK cascade behavior (delete parent FOV → verify cascades)
- [ ] Add tests for lineage_path backfill correctness
- [ ] Create shared `conftest.py` for percell4 tests to reduce fixture duplication
- [ ] Verify all existing tests pass (~5-10% expected to need updating, not 30-50%)

### Review Findings (Run 1)

**Critical:**
- PLAN-VS-CODE MISMATCH: The plan describes creating `cell_identities`, `rois`, `fov_status_log` tables and renaming `cells` to `rois`, but ALL of these already exist in schema 5.1.0 on `feat/percell4-gate0`. There was never a `cells` table in percell4. The actual 6.0.0 delta is only: add 5 columns to `fovs` (`lineage_depth`, `lineage_path`, `display_name`, `channel_metadata`, `pipeline_run_id`), create `workflow_configs` table, add `fovs(lineage_path)` index, and backfill existing FOVs. Redefine Step 2 as "Schema 6.0.0 Delta" to avoid redundant work and regression risk. [architecture-strategist, data-migration-expert, schema-drift-detector, repo-research-analyst, python-reviewer, pattern-recognition-specialist]
- `lineage_path` column is missing from 5.1.0 schema and is required for fast subtree queries. This is the single most important schema delta. Must include index `CREATE INDEX idx_fovs_lineage_path ON fovs(lineage_path) WHERE lineage_path IS NOT NULL`. [architecture-strategist, data-migration-expert]
- `FovInfo` model has `display_name: str` field but schema has no `display_name` column — latent model-schema mismatch causing potential runtime errors. [repo-research-analyst, python-reviewer]
- `FovInfo` model is missing `derivation_params` field even though schema stores it — data silently dropped at API boundary. [python-reviewer]

**Serious:**
- Step 5a incorrectly says to "create cell_identities for cells in derived FOVs." Cell identities are created ONCE at original segmentation, then REUSED (same `cell_identity_id`) across derived FOVs. Creating new ones breaks cross-FOV queries. Fix wording to "PRESERVE existing cell_identity_id references." [architecture-strategist]
- No ON DELETE CASCADE/RESTRICT rules on any foreign key. Deleting a parent FOV will silently orphan all children. Add explicit cascade rules during migration. [data-integrity-guardian]
- `cell_identities.origin_fov_id` has no cascade rule — deleting an origin FOV breaks the cell identity anchor for all downstream derived FOVs. Use ON DELETE RESTRICT. [data-integrity-guardian]
- The derived FOV four-step contract has no atomicity guarantee. Steps 2-4 (DB operations) must be wrapped in a single `db.transaction()`, with Zarr cleanup on failure. [data-integrity-guardian]
- `lineage_path` data format not specified. Standardize on `hex(id)` segments (32 chars, no hyphens) separated by `/`. Document explicitly. [data-migration-expert]
- Plan omits existing 5.1.0-only tables (`roi_type_definitions`, `segmentation_sets`, `fov_segmentation_assignments`, `fov_mask_assignments`, `threshold_masks`, `timepoints`, `pipeline_runs`) — must explicitly state they persist in 6.0.0. [schema-drift-detector]
- `cell_identities` differs between P-body spec (has `experiment_id`, `origin_label_id`) and 5.1.0 schema (has `roi_type_id` instead). Must reconcile. [schema-drift-detector, python-reviewer]
- `MERGE_TABLE_ORDER` has `pipeline_runs` after tables that reference it — FK violation risk during merge. Move `pipeline_runs` before referencing tables. [data-integrity-guardian]
- P-body architecture spec uses `TEXT PRIMARY KEY` for UUIDs but codebase uses `BLOB(16)`. New tables (e.g., `workflow_configs`) must use BLOB(16) — do NOT copy DDL from P-body spec without converting. [python-reviewer, schema-drift-detector, performance-oracle]
- Test breakage estimate of 30-50% is overstated. Since `cells->rois` rename is already done, actual impact is ~5-10% (tests constructing FovInfo with new fields, insert_fov signature changes, new table tests). [repo-research-analyst, architecture-strategist]
- Plan does not scope viewer module call site updates (30+ `store.db.*` calls). Schema changes in Step 2 will break these. Add explicit sub-step. [architecture-strategist]

**Recommendations:**
- Wrap migration in explicit transaction with `PRAGMA foreign_key_check` after migration. [best-practices-researcher, data-migration-expert]
- Add backfill strategy for `lineage_path` on existing FOVs. Root FOVs get `hex(id)`, derived FOVs iteratively built from parent paths. [data-migration-expert]
- Add post-migration verification queries (no orphaned lineage_path, depths consistent, paths end with hex(id)). [data-migration-expert]
- Consider deferring `workflow_configs` table from Step 2 to Step 6 — it is not consumed until Step 6 and is purely additive. [code-simplicity-reviewer]
- Consider deferring `fov_status_log` enhancements — the table already exists with adequate `old_status`/`new_status` design. Only add `pipeline_run_id` if needed. [code-simplicity-reviewer, python-reviewer]
- Add `origin_label_id` to `cell_identities` table for convenience queries ("Cell #47") without 3-table join. [python-reviewer]
- Define `workflow_configs` DDL explicitly with BLOB(16) PK, `CHECK(json_valid(config_json))`, and `UNIQUE(experiment_id, workflow_name)`. [data-migration-expert]
- Add new exception subclasses: `RoiNotFoundError`, `LineageError`, `WorkflowConfigError`. [pattern-recognition-specialist]
- New dataclasses should follow gate0's `frozen=True, slots=True, kw_only=True` pattern. [pattern-recognition-specialist]
- Create shared `conftest.py` for percell4 tests to reduce fixture duplication. [repo-research-analyst]
- Add `PRAGMA trusted_schema=OFF` to connection configuration before migration. [security-sentinel]
- Add `isidentifier()` check on column names from `PRAGMA table_info` in merge conflict detection. [security-sentinel]

---

## Step 3: Basic UX Fixes + Banner

**Gate target: end-to-end workflow functional from menu**

### 3a. ASCII Banner

- [ ] Port percell3 ASCII banner from `src/percell3/cli/menu.py` (lines 1332-1372) to percell4 `menu_system.py`
- [ ] Update version text: "PerCell 3.0" → "PerCell 4.0"
- [ ] Apply colorization: cyan (microscope), green (PER), magenta (CELL) using Rich markup

### 3b. Status-Unlocked Handlers

- [ ] Update `segment_handler()`: show all active FOVs (not just `imported`), let user select
- [ ] Update `measure_handler()`: show all active FOVs (not just `segmented`), let user select
- [ ] Update CLI `segment` command: add `--all` flag to process all FOVs regardless of status
- [ ] Update CLI `measure` command: add `--all` flag
- [ ] Add permissive status transitions for re-processing (e.g., `measured → segmented`, `analyzed → segmented`) or use `stale` as intermediate re-entry state — current `VALID_TRANSITIONS` will raise `InvalidStatusTransition` when users try to re-segment a measured FOV

### 3c. Condition Management

- [ ] Add `[[conditions]]` section to TOML template (both `init` command and `_generate_template_toml`)
- [ ] Add condition prompt during import (list existing conditions, option to create new)
- [ ] Add bio rep prompt during import (list existing, option to create new)
- [ ] Deduplicate TOML template generation: extract `_default_toml_lines(include_comments)` shared function

### 3d. FOV Selection Helpers

- [ ] Port `numbered_select_one()` helper from percell3 `menu.py` for single FOV selection
- [ ] Port `numbered_select_many()` helper for multi-FOV selection
- [ ] Use in segment, measure, and plugin handlers

### Review Findings (Run 1)

**Serious:**
- Rich markup can consume special characters (brackets) in menu output. Use `\\[` escaping for menu letter keys, verified pattern from prior CLI bug fix. [learnings-researcher]

**Recommendations:**
- ASCII banner is cosmetic — do not let it block Step 3 completion. [code-simplicity-reviewer]
- Status machine `VALID_TRANSITIONS` enforcement should remain for data integrity even though handlers stop filtering by status — these are different concerns. [repo-research-analyst]
- Add `sanitize_filename()` helper for export paths using database-derived values (condition names, channel names). [security-sentinel]

---

## Step 4: Menu Reorganization

**Gate target: 8-item menu matching brainstorm layout**

### 4a. Restructure Main Menu

- [ ] Reorganize `build_main_menu()` to 8 items: Setup, Import/Export, Segment, Analyze, View, Config, Workflows, Plugins
- [ ] Merge Import and Export into single submenu
- [ ] Move Export CSV, Export Prism into Import/Export submenu
- [ ] Add Export TIFF handler (port from percell3)
- [ ] Add Workflows submenu with particle analysis and decapping sensor handlers
- [ ] Add Config submenu (placeholder items initially)

### 4b. Config Manager

- [ ] Create `menu_handlers/config.py`
- [ ] Assignment matrix view: show which segmentations/thresholds are assigned to which FOVs
- [ ] Condition CRUD: create, rename, delete conditions
- [ ] Bio rep CRUD: create, rename, delete bio reps
- [ ] FOV metadata: rename FOV, delete FOV, view pixel_size_um
- [ ] Workflow config: placeholder with "coming in Step 6"

### 4c. Workflow Menu Handlers

**NOTE: Step 4c depends on Step 5 (plugin rewrites).** The decapping sensor workflow calls plugins that are being rewritten in Step 5. Implement Step 4c workflow handlers AFTER Step 5, or implement with placeholder plugin calls that get updated in Step 5.

- [ ] Create `menu_handlers/workflow.py`
- [ ] Particle analysis handler: FOV selection → run workflow → show results
- [ ] Decapping sensor handler: FOV selection → run workflow → show results
- [ ] Wire workflow engine to menu handlers with progress reporting

### Review Findings (Run 1)

**Serious:**
- FOV deletion is destructive (cascades to ROIs, measurements, assignments, Zarr data). Placing it in "Config" alongside non-destructive operations risks accidental deletions. Add double-confirmation or move to "Advanced" sub-item. [architecture-strategist]

**Recommendations:**
- Config Manager CRUD (condition/bio-rep/FOV) is polish, not critical path. Consider reducing Step 4b to read-only assignment matrix for MVP. [code-simplicity-reviewer]
- TOML `[[pipelines]]` defines static pipeline topology; `workflow_configs` in DB stores runtime parameters. Clarify this composition model in Step 6 notes. [architecture-strategist]

---

## Step 5: Plugin Rewrites

**Gate target: all plugins use lineage model and store measurements in DB**

### 5a. Derived FOV Contract Update

- [ ] Update the derived FOV creation contract to use `store.derive_fov()` (from Step 2d)
- [ ] All derived FOVs must set: `parent_fov_id`, `derivation_op`, `derivation_params`, `lineage_depth`, `lineage_path`
- [ ] All plugins creating derived FOVs must PRESERVE existing `cell_identity_id` references when duplicating ROIs (do NOT create new cell_identities — they are created once at segmentation)
- [ ] Extract `save_edited_labels()` from viewer to public `store_labels_and_rois()` function

### 5b. condensate_partitioning_ratio Rewrite

- [ ] Update to use `rois` table instead of `cells`
- [ ] Save scalar results (ratios) as measurements with metric names: `cpr_inside_ratio`, `cpr_outside_ratio`, `cpr_condensate_fraction`
- [ ] Write custom menu handler with channel selection prompts (port from percell3's `_run_condensate_partitioning_ratio()`)
- [ ] Update tests

### 5c. image_calculator Update

- [ ] Update to create derived FOVs with lineage (`derivation_op="image_calculator_{operation}"`)
- [ ] PRESERVE existing `cell_identity_id` when duplicating ROIs to derived FOV (do NOT create new cell_identities)
- [ ] Absorb nan_zero functionality: add "nan_zero" as an operation type
- [ ] Write custom menu handler (port from percell3's `_run_image_calculator()`)
- [ ] Update tests

### 5d. local_bg_subtraction Update

- [ ] Update to create derived FOVs with lineage (`derivation_op="local_bg_subtraction"`)
- [ ] Save BG-subtracted values as measurements
- [ ] PRESERVE existing `cell_identity_id` when duplicating ROIs to derived FOV
- [ ] Write custom menu handler (port from percell3's `_run_bg_subtraction()`)
- [ ] Update tests

### 5e. split_halo_condensate_analysis Update

- [ ] Update to create derived FOVs with lineage (`derivation_op="split_halo_analysis"`)
- [ ] Save scalar results as measurements
- [ ] PRESERVE existing `cell_identity_id` when duplicating ROIs to derived FOV
- [ ] Write custom menu handler (port from percell3's `_run_condensate_analysis()`)
- [ ] Update tests

### 5f. threshold_bg_subtraction Redesign

- [ ] Implement new algorithm: per-group BG from ROI-bounded + dilute-mask pixels
- [ ] Histogram estimation of BG per intensity group
- [ ] Single derived FOV per parent: each cell subtracted by group BG, NaN outside ROIs
- [ ] PRESERVE existing `cell_identity_id` when duplicating ROIs to derived FOV
- [ ] `derivation_op="threshold_bg_subtraction"`
- [ ] Write custom menu handler
- [ ] Update tests with known BG values to verify correctness

### 5g. Remove nan_zero Standalone Plugin

- [ ] Remove `nan_zero.py` from plugins directory
- [ ] Remove from plugin registry
- [ ] Update any tests that reference nan_zero as standalone
- [ ] Verify nan_zero functionality accessible through image_calculator

### 5h. surface_plot_3d — Keep As-Is

- [ ] Update to use `rois` instead of `cells` (if applicable)
- [ ] Verify still works with new schema
- [ ] Write visualization plugin menu handler

### Review Findings (Run 1)

**Critical:**
- Step 5a WORDING ERROR: "create cell_identities for cells in derived FOVs" is WRONG. Cell identities are created ONCE at original segmentation, then REUSED across all derived FOVs. Fix to: "PRESERVE existing cell_identity_id references when duplicating ROIs to derived FOVs." [architecture-strategist]

**Serious:**
- `create_derived_fov()` already handles most lineage on gate0 (reads source, transforms channels, writes zarr, inserts FOV with parent_fov_id, copies assignments, duplicates ROIs preserving cell_identity_id). Only missing: `lineage_depth`, `lineage_path`, `display_name`, `channel_metadata`. Not a full rewrite. [repo-research-analyst]
- Derived FOV full-image copy creates O(channels x image_size) memory pressure. For 6-channel 2048x2048 FOVs: ~192MB peak. Consider chunk-level Zarr copy for unchanged channels. [performance-oracle]
- Before removing `nan_zero`, grep for all string references to `"nan_zero"` in workflows, tests, and menu handlers to prevent runtime `PluginError`. [pattern-recognition-specialist]
- Plugins like `condensate_partitioning_ratio` and `surface_plot_3d` need updates, not rewrites. Rename "Rewrite" to "Update" for correct effort estimates. [code-simplicity-reviewer]
- Only plugins creating user-queryable derived FOVs need cell_identities population. `condensate_partitioning_ratio` (scalar results only) and `surface_plot_3d` (visualization) do not. [code-simplicity-reviewer]

**Recommendations:**
- Separate `_core.py` (pure math) from plugin class (store I/O) for all plugins. [learnings-researcher, context-researcher]
- Provide bulk `insert_cell_identities()` and bulk `insert_rois()` using `executemany()` to avoid N+1 insert patterns. [performance-oracle]
- Use `is None` for all optional parameter checks, not truthiness. [context-researcher]
- Validate `config_json` for `workflow_configs` against Pydantic schema before storage. [security-sentinel]
- Plugin ABC: either implement `get_parameter_schema()` with JSON Schema for generic rendering, or skip the ABC change entirely and rely on per-plugin menu handlers. Do not implement `get_required_parameters()` as a half-measure. [python-reviewer]

---

## Step 6: Workflow Config

**Gate target: workflow parameters editable from Config menu**

- [ ] Create `workflow_configs` table with BLOB(16) PK, `CHECK(json_valid(config_json))`, `UNIQUE(experiment_id, workflow_name)` (deferred from Step 2)
- [ ] Add `WorkflowConfig` dataclass (`frozen=True, slots=True, kw_only=True`), `WorkflowConfigError` exception
- [ ] Implement `workflow_configs` CRUD in ExperimentDB: `insert_workflow_config()`, `get_workflow_configs()`, `update_workflow_config()`
- [ ] Add workflow config UI to Config Manager submenu
- [ ] Allow editing workflow parameters (model, diameter, threshold values, channel selections)
- [ ] Wire workflow engine to read parameters from DB instead of hardcoded defaults
- [ ] Update particle analysis workflow to use configurable parameters
- [ ] Update decapping sensor workflow to use configurable parameters
- [ ] Add CLI `percell4 workflow list` and `percell4 workflow run <name>` commands

### Review Findings (Run 1)

**Serious:**
- TOML `[[pipelines]]` defines static pipeline topology, while `workflow_configs` in DB stores runtime parameters. Plan does not clarify how these compose. Add note: "Workflow engine reads topology from TOML, parameters from DB, falling back to TOML defaults when no DB override exists." [architecture-strategist]

**Recommendations:**
- This entire step is deferrable for MVP. The plan's own Deferred section says Steps 1-3 are minimum viable. Consider removing acceptance criterion #12 (configurable workflow parameters) from the main acceptance criteria and making it a Step 6 deliverable. [code-simplicity-reviewer]
- Use optimistic locking (`updated_at` as version check) for concurrent `workflow_configs` updates to prevent silent overwrites. [data-integrity-guardian]

---

## Acceptance Criteria

1. NaN pixels handled correctly through measurement/display/export pipeline (Step 1 spike validates)
2. Schema 6.0.0 with full P-body model: cell_identities, rois, lineage, status log, workflow configs
3. All existing tests updated and passing with new schema
4. ASCII banner matches percell3 visual identity
5. Segment and measure handlers work on any FOV regardless of status
6. Conditions and bio reps manageable from menu (create, assign during import, CRUD in Config)
7. Menu has 8 top-level items: Setup, Import/Export, Segment, Analyze, View, Config, Workflows, Plugins
8. Config manager shows assignment matrix, condition/bio rep CRUD, FOV metadata
9. All 6 plugins rewritten with lineage model and measurement storage
10. threshold_bg_subtraction produces single derived FOV with per-cell group-specific BG subtraction
11. nan_zero absorbed into image_calculator
12. Workflows accessible from menu and CLI with configurable parameters
13. Each plugin has a custom menu handler with parameter prompts
14. Percell4 is a clean break — no percell3 migration support needed

### Review Findings (Run 1)

**Recommendations:**
- Criteria #4 (ASCII banner) and #8 (Config manager CRUD) are cosmetic/polish — mark as nice-to-have for MVP. [code-simplicity-reviewer]
- Criterion #12 (configurable workflow parameters) is Step 6 content — consider making it a Step 6 deliverable, not a top-level acceptance criterion. [code-simplicity-reviewer]
- Add criterion: "CLAUDE.md Key Domain Terms updated to reflect ROI terminology shift." [pattern-recognition-specialist]
- Add criterion: "All new CRUD methods follow parameterized query pattern (no string interpolation for user data)." [security-sentinel]

---

## Deferred

1. **NaN edge cases** — deferred to Step 1 spike. If spike reveals problems, revisit threshold_bg_subtraction design.
2. **nan_zero as image_calc vs napari widget** — will decide during Step 5c implementation.
3. **Minimum viable definition** — Steps 1-3 are the minimum for a functional tool. Steps 4-6 bring full feature parity.

### Review Findings (Run 1)

**Recommendations:**
- Add to deferred: napari widgets (Experiment Navigator, Cell Inspector, Export Builder, Group Manager) referenced in P-body architecture but not scoped in this plan. [context-researcher]
- Add to deferred: `purge_deleted_fovs()` method for cleaning up soft-deleted FOV tombstones and reclaiming space via VACUUM. [data-integrity-guardian]
- Add to deferred: chunk-level Zarr copy for unchanged channels in derived FOVs (performance optimization). [performance-oracle]
- Add to deferred: `analysis_dashboard` view defined in P-body spec but not mentioned in plan. [schema-drift-detector]
- Add to deferred: `polygon TEXT` column on rois table (in P-body spec, not in current schema or plan). [python-reviewer]

---

## Sources

- **Origin brainstorm:** `docs/brainstorms/2026-03-10-percell4-completion-brainstorm.md` — Key decisions: full P-body schema (6.0.0), clean break, status informational only, plugin results as measurements, priority reorder after red team
- **P-body architecture:** `docs/plans/percell_pbody_architecture.md` — Schema DDL, cell_identities, rois, intensity groups, lineage model, workflow config TOML
- **Code review:** `.workflows/code-review/percell4-rewrite/agents/comprehensive-review.md` — 20 findings (5 P1, 9 P2, 5 P3)
- **Design gaps:** `docs/solutions/design-gaps/percell4-rewrite-ux-and-architecture-review.md` — Status-locked handlers, condition management, plugin params, viewer facade bypass
- **Repo research:** `.workflows/brainstorm-research/percell4-completion/repo-research.md` — Percell3 vs percell4 feature comparison, 23-item completion checklist
- **Red team review:** `.workflows/brainstorm-research/percell4-completion/red-team--opus.md` — 1 CRITICAL (NaN load-bearing), 7 SERIOUS (schema scope, contradictions, test breakage)
- **Viewer code review (percell3):** `docs/solutions/architecture-decisions/viewer-module-code-review-findings.md`
- **Layer-based architecture:** `docs/solutions/architecture-decisions/layer-based-architecture-redesign-learnings.md`
- **Deepen-plan run 1:** `.workflows/deepen-plan/feat-percell4-completion/run-1-synthesis.md` — 13-agent review + red team. Key corrections: schema delta much smaller than planned, cell_identity preservation, NaN spike additions, measurement engine gap, viewer scoping.
- **Red team (deepen-plan):** `.workflows/deepen-plan/feat-percell4-completion/agents/run-1/red-team--opus.md` — 2 CRITICAL (measurement engine, FovInfo model), 10 SERIOUS (NaN storage, pixel_size_um, status transitions, viewer updates)
