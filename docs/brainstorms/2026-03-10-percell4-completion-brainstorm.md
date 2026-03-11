---
title: "PerCell4 Completion — Making It Functional"
date: 2026-03-10
topic: percell4-completion
---

# PerCell4 Completion Brainstorm

## What We're Building

Complete the percell4 rewrite to make it a functional replacement for percell3. The codebase (131 files, ~26K lines, 628 tests) has strong architecture but significant UX gaps that prevent end-to-end usage. This brainstorm captures the user's vision for what "functional" means.

Percell4 is a **clean break** from percell3 — no migration path for existing `.percell` experiments. New experiments only.

## Key Decisions

### 1. ASCII Banner (from percell3)

Port the percell3 ASCII banner (microscope + colorized PERCELL lettering) to percell4, updating version number. This is the visual identity of the tool.

**Rationale:** The banner provides immediate recognition for existing percell3 users and makes the tool feel polished.

### 2. Menu Structure (8 items, reorganized)

```
MAIN MENU
  1. Setup          -> Create experiment, Open experiment, Generate TOML template
  2. Import/Export   -> Import images, Import from PerCell, Export CSV, Export Prism, Export TIFF
  3. Segment        -> Segment cells (all FOVs, not status-locked)
  4. Analyze        -> Measure channels, Grouped intensity thresholding
  5. View           -> Open napari viewer
  6. Config         -> Assignment matrix, Conditions/bio reps, FOV metadata,
                       Workflow config (placeholder until workflows built)
  7. Workflows      -> Particle analysis, Decapping sensor
  8. Plugins        -> Dynamic list with plugin-specific parameter prompts
```

**Key differences from percell3:**
- Import and Export merged into one category (percell3 had them split across "Import" and "Data")
- "Data" replaced with "Config" — manages assignments, conditions, FOV metadata, and workflow parameters
- Config manager is the central place for the layer-based architecture's fov_config matrix

**Rationale:** The user wants the same UX feel as percell3 (8 top-level items, submenus for details) but reorganized to match percell4's architecture where configuration (assignments, conditions) is more central than in percell3's run-scoped model.

### 3. Plugin Rewrites

All plugins get rewritten (not just re-ported) with these changes:

| Plugin | Change |
|--------|--------|
| `condensate_partitioning_ratio` | Save scalar results to DB as measurements (plugin-specific metric names) |
| `image_calculator` | Derived FOVs attached to parent via full P-body lineage model |
| `local_bg_subtraction` | Derived FOVs attached to parent + save scalar results to DB as measurements |
| `split_halo_condensate_analysis` | Derived FOVs attached to parent + save scalar results to DB as measurements |
| `threshold_bg_subtraction` | **Major redesign** (see section 3a below) |
| `nan_zero` | **Removed as standalone plugin.** Functionality absorbed into `image_calculator` or a dedicated napari widget. |
| `surface_plot_3d` | Keep as-is (visualization plugin) |

**Rationale:** The user wants derived FOVs to maintain lineage to their parent (full P-body model). Plugin scalar results are measurements and go into the existing measurements table with plugin-specific metric names — no new table needed. Derived FOV creation is already handled by the existing contract.

### 3a. threshold_bg_subtraction Redesign

**Old model (percell3):** Per-group derived FOVs. Each intensity group gets its own derived FOV with pixels masked by the group's threshold mask. Histogram of all masked pixels in the group estimates background.

**New model (percell4):**
- **Single derived FOV per parent FOV** — no more per-group FOVs
- **Per-group BG estimation using ROI-bounded pixels:** For each group (e.g., cells 3, 5, 6 in a group), collect pixels that are BOTH inside those cells' segmentation ROIs AND inside the dilute phase mask. Plot histogram of those pixels to estimate the group's background value.
- **Per-cell BG subtraction:** Each cell's pixels are subtracted by its group's estimated BG value
- **NaN outside ROIs:** Everything outside segmentation ROIs in the derived FOV is NaN
- **Group identity from DB:** Cell-to-group assignments are read from the database (not from threshold mask geometry)

**Rationale:** This approach uses the segmentation ROIs as the spatial boundary (not the threshold mask), which is more precise. The group identity is a database concept, not a spatial one. The single derived FOV simplifies downstream analysis.

### 4. Schema: Full P-body Model (6.0.0)

Adopt the full P-body architecture schema. This is NOT just "add lineage columns" — it includes:
- `parent_fov_id`, `derivation_op`, `derivation_params`, `lineage_path` on `fovs` table
- `cell_identities` table for stable cell identity across derived FOVs
- Renaming `cells` to `rois` with `cell_identity_id` foreign key
- `fov_status_log` table for status transition tracking
- Updated measurement joins through the new `rois` table
- `workflow_configs` table for workflow parameter storage

**Schema version:** 5.1.0 → 6.0.0 (major version bump — architectural change)

**Test impact:** ~30-50% of 628 existing tests will need modification. This cost is accepted as part of the migration.

**Migration story:** Clean break — percell4 is for new experiments only. No percell3-to-percell4 migration.

**Rationale:** The user wants the full P-body model, not an incremental half-measure. The test breakage cost is accepted upfront to avoid accumulating technical debt from partial schema migrations.

### 5. Status Model: Informational, Not Gating

Status is tracked for the dashboard view (`imported → segmented → measured → analyzed`) but handlers do NOT gate on status. Segment and measure handlers work on ALL active FOVs with user selection.

**Rationale:** Re-segmentation and re-measurement are the most common real-world operations. Status is informational context, not a workflow gate. (Red team flagged the tension between status tracking and status-unlocked handlers — resolved by making status informational only.)

### 6. Napari Widgets — Current Set is Sufficient

The 8 current widgets are sufficient for this phase. The percell3 widgets for copy_labels, copy_masks, bg_subtraction, and surface_plot are **not needed** now.

### 7. Plugin Parameter Prompts

Each plugin needs a custom interactive handler (like percell3's 7 handlers) that prompts for plugin-specific parameters. The current generic `_make_plugin_runner()` is insufficient.

### 8. Priority Order (dependency-ordered)

1. **NaN spike** — Validate NaN pixel behavior through measurement/display/export pipeline before committing to threshold_bg_subtraction redesign
2. **Schema 6.0.0 migration** — Full P-body model (prerequisite for everything that follows)
3. **Basic UX fixes + banner** — Status-unlocked handlers, condition management, TOML template with conditions, ASCII banner
4. **Config manager** — Assignment matrix, conditions/bio reps, FOV metadata
5. **Plugin rewrites** — All plugins rewritten with lineage model and DB measurement storage
6. **Workflows** — Particle analysis and decapping sensor accessible from menu + CLI
7. **Workflow config** — Parameter configuration stored in DB, editable from Config menu

**Rationale:** Red team identified hidden dependencies in the original order. Schema migration must come before anything that depends on the new tables (config manager, plugins). NaN spike must come before the threshold_bg_subtraction redesign since the entire single-derived-FOV approach depends on correct NaN handling.

## Resolved Questions

1. **Schema migration scope:** → **6.0.0 with full P-body model.** Not just lineage columns — includes cell_identities, rois (replacing cells), status_log, workflow_configs. Accepted ~30-50% test breakage.

2. **Workflow config storage:** → **SQLite DB.** `workflow_configs` table, editable from Config menu. TOML is read-once at creation; runtime config lives in the DB.

3. **Plugin results in DB:** → **Existing measurements table.** Plugin scalar results are measurements with plugin-specific metric names. Derived FOV creation handled by existing contract. (Red team noted this potentially conflicts with P-body model's new measurement joins — the measurements table will be updated as part of schema 6.0.0 to join through `rois` instead of `cells`.)

4. **Per-cell BG estimation:** → **Group-bounded ROI pixels + dilute mask.** For each intensity group, collect pixels inside the group's cell ROIs AND inside the dilute phase mask. Histogram estimates BG per group. Each cell subtracted by its group's BG value. NaN outside all ROIs.

5. **Percell3 migration:** → **Clean break.** Percell4 is for new experiments only.

6. **Status gating:** → **Informational only.** Status tracked for dashboard, not used to gate handlers.

7. **Priority dependencies:** → **Reordered.** NaN spike → Schema → UX fixes → Config → Plugins → Workflows → Workflow config.

## Deferred Questions

1. **NaN edge cases:** What happens with all-NaN ROIs or ROIs at image edges in the threshold_bg_subtraction derived FOV? **Deferred to NaN spike** (priority step 1) — will validate experimentally before committing to the redesign.

## Red Team Findings (Acknowledged MINOR)

- "Rewrite" vs "targeted modification" — clarify during planning which plugins need full rewrites vs integration changes
- nan_zero placement (image_calc vs napari widget) — decide during plugin rewrite phase
- No minimum viable definition — planning phase will define cut lines
- Import/Export merge might need splitting — accept for now, split if submenus get too crowded

## Sources

- Repo research: `.workflows/brainstorm-research/percell4-completion/repo-research.md`
- Red team review: `.workflows/brainstorm-research/percell4-completion/red-team--opus.md`
- Code review: `.workflows/code-review/percell4-rewrite/agents/comprehensive-review.md`
- Design gaps: `docs/solutions/design-gaps/percell4-rewrite-ux-and-architecture-review.md`
- P-body architecture: `docs/plans/percell_pbody_architecture.md`
- Percell3 menu reference: `src/percell3/cli/menu.py` (~2000 lines)
