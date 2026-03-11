# Brainstorm: P-body Architecture Refactor

**Date:** 2026-03-10
**Status:** Complete
**Related:** `docs/plans/percell_pbody_architecture.md`, `docs/plans/uuid_vs_integer_agent_answer.md`

---

## What We're Building

A phased refactor of PerCell 3's data layer to support complex multi-step analysis workflows (P-body sensor assay as the driving use case). New schema with FOV lineage, stable cell identity, experiment-defined ROI types, first-class intensity groups, and assignment tables with provenance. Engine code (measurer, segmenter, IO readers) is reused with interface changes. CLI gets a complete rewrite preserving visual style.

**Scope for v1:** Schema + three-layer ExperimentStore split + updated engines + CLI orchestration. TOML pipeline runner and napari widgets deferred to subsequent phases.

---

## Key Decisions

### 1. Phased Refactor, Not Rewrite

**Decision:** New data layer, reuse engine code. Develop on a dedicated feature branch; `main` stays stable (1,363 tests passing as of 2026-03-10).

**Rationale:** The engine code (measurer.py, metrics.py, particle_analyzer.py, Cellpose adapter, IO readers) is well-tested and solves real problems. The schema and orchestration layer is what needs to change. A full rewrite would throw away working code and repeat the risk pattern of prior refactors.

### 2. UUID as BLOB(16) for All Entity Tables

**Decision:** Use `uuid.uuid4().bytes` stored as `BLOB(16)` for every entity table. Integer IDs only for log tables (`fov_status_log`, `pipeline_run_log`) and junction tables (`cell_group_assignments`).

**Rationale:** PerCell is lab-shared software (3-6 researchers) where database merging is a first-class feature. With UUID PKs, merging is `INSERT OR IGNORE` via `ATTACH`. Integer PKs would require full FK remapping on every merge. ML training data export also requires globally stable IDs. See `docs/plans/uuid_vs_integer_agent_answer.md` for full analysis.

**Do NOT use hybrid approach** (integer PK + UUID column). It solves nothing — foreign keys still use integers, so merges still require remapping.

### 3. Unified ROIs Table with Experiment-Defined Types

**Decision:** Single `rois` table with `roi_type_id` FK to `roi_type_definitions` table. Replaces separate `cells` and `particles` tables.

**Rationale:** The P-body workflow produces 3+ named sub-cellular ROI types per experiment (P-bodies, out-of-focus P-bodies, dilute phase foci). These types are experiment-specific, not hardcodeable. Separate tables per type would require N identical code paths and new tables per experiment.

**`roi_type_definitions`** is a first-class DB table populated from TOML config on experiment creation. Each type has: name, display_name, parent_type_id (NULL for cells, cell type ID for sub-cellular), color, sort_order.

**Each segmentation config declares `produces_roi_type`.** The pipeline runner uses this to tag ROIs at creation time.

### 4. Single Facade, Three Internal Layers

**Decision:** `ExperimentStore` remains the sole public API. CLI and napari widgets never import `ExperimentDB`, `LayerStore`, or `AssignmentService` directly. The three layers are an internal decomposition.

```
CLI / napari
      |
      v
ExperimentStore (facade)
      |
      +---> ExperimentDB    (SQLite only, no Zarr knowledge)
      +---> LayerStore       (Zarr only, no SQL knowledge)
      +---> AssignmentService (reads DB, no Zarr writes)
```

**Strict dependency rule:**
- `LayerStore`: no SQL imports
- `ExperimentDB`: no Zarr imports
- `AssignmentService`: calls `ExperimentDB` only, no Zarr
- `ExperimentStore`: orchestrates all three, owns atomicity

**Refactor sequence:** LayerStore extraction -> ExperimentDB extraction -> AssignmentService introduction -> schema additions. Each phase independently testable.

### 5. Write-Ahead DB for Dual-Store Atomicity

**Decision:** For operations that write both DB and Zarr (e.g., `derive_fov`):
1. Write DB record with `status='pending'`
2. Write Zarr data
3. Update DB status to committed value

On startup, `ExperimentStore` runs recovery: check all `status='pending'` records, promote or mark as error based on whether Zarr path exists.

**Rationale:** Cannot have distributed transactions across SQLite and filesystem. The status field acts as a commit flag. Standard write-ahead pattern adapted for two-store system.

### 6. Assignment Tables Replace fov_config

**Decision:** `fov_config` is replaced by `fov_segmentation_assignments` and `fov_threshold_assignments`. Each carries:
- `is_active` flag (current state)
- `pipeline_run_id` FK (provenance)
- `assigned_by` enum ('pipeline_run' | 'user_manual' | 'user_copy' | 'merge')
- `roi_type_id` FK (scoped per ROI type)

**Source of truth split:**
- **Current state:** assignment tables (`is_active = 1`)
- **Provenance:** `pipeline_runs` record, referenced by FK on assignment row
- **Intent:** TOML pipeline topology

All three coexist. Do not collapse them.

**`AssignmentService`** owns all reads/writes to assignment tables. Pipeline runner calls `ExperimentStore`, which delegates to `AssignmentService`.

**A single FOV has multiple active assignments** — one per ROI type. This is correct and expected.

### 7. CLI Complete Rewrite, Preserve Visual Style

**Decision:** CLI menu code gets completely rewritten for the new API. The visual identity (Rich styling, colors, menu layout, graphics) stays the same.

### 8. Start Fresh, No Migration

**Decision:** New experiments use the new schema. Old experiments stay on `main` branch code. No schema migration needed.

**Rationale:** Existing experiments are mostly complete. Migration would require generating UUIDs for every integer PK and remapping every FK — high risk for low value.

---

## Architecture Components (from the P-body Architecture Doc)

These are carried forward from `docs/plans/percell_pbody_architecture.md` and refined during this brainstorm:

- **FOV Lineage Tree:** `parent_fov_id`, `lineage_path`, `lineage_depth`, `derivation_op`, `derivation_params` on `fovs` table
- **Cell Identities:** `cell_identities` table with stable UUID per physical cell, anchored to origin FOV
- **Intensity Groups:** `intensity_groups` table with `is_excluded` flag, `cell_group_assignments` junction table (replaces tag-encoded groups)
- **FOV Status Machine:** `status` column on `fovs` + `fov_status_log` table for transition history
- **Automatic FOV Naming:** Config-driven suffix table, `auto_name` constructed at derivation time
- **Measurements:** Long/narrow format `(roi_id, channel_id, metric, value, scope)` — never wide

---

## Resolved Questions

**Q: Is this a rewrite or refactor?**
A: Phased refactor — new data layer, reuse engine code. User's reasoning: "as long as I can keep a stable version to continue to perform some level of analysis I'm okay with a complete rewrite if necessary." Phased approach gives stability without throwing away working engines.

**Q: Why UUIDs instead of integers?**
A: Lab-shared software with database merging. `INSERT OR IGNORE` via ATTACH requires globally unique PKs. See `docs/plans/uuid_vs_integer_agent_answer.md`.

**Q: Why unified ROIs instead of separate cells/particles tables?**
A: Experiment-defined ROI types (P-bodies, out-of-focus P-bodies, dilute phase foci) mean you can't hardcode table names. Separate tables would require N identical code paths. The unified table with `roi_type_definitions` handles arbitrary types with one code path.

**Q: Does fov_config survive?**
A: No. Replaced by `fov_segmentation_assignments` and `fov_threshold_assignments` with provenance links. The old table conflated assignments and configuration state into one rigid matrix. New tables separate current state, provenance, and intent.

**Q: How is dual-store atomicity handled?**
A: Write-ahead DB pattern. DB record written first with `status='pending'`, Zarr written second, DB status updated to committed value on success. Recovery on startup checks pending records.

---

## Open Questions

None — all questions resolved during brainstorm.

---

## Sources

- `docs/plans/percell_pbody_architecture.md` — original architecture proposal
- `docs/plans/uuid_vs_integer_agent_answer.md` — UUID rationale
- `docs/solutions/architecture-decisions/layer-based-architecture-redesign-learnings.md` — lessons from prior refactor
- `docs/solutions/design-gaps/derived-fov-lifecycle-coordination.md` — 4-step derived FOV contract
- `.workflows/brainstorm-research/pbody-architecture-refactor/repo-research.md` — codebase impact analysis
- `.workflows/brainstorm-research/pbody-architecture-refactor/context-research.md` — project knowledge synthesis
